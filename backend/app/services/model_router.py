"""Model Router credentials: config shape, routing decisions, option binding.

A model router does not hold a key of its own. It holds a decision model
credential, a list of options (each an existing LLM credential plus a model id)
and free text per option saying when that option should win. At request time the
decision model answers one `choice` question and the winning option's credential
is bound for that provider call.

Everything that knows the router's config shape lives here, the way
`decision_models.py` is the only module that knows the System One wire format.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, replace

from app.db.models import Credential, CredentialType
from app.db.session import SessionLocal
from app.services.decision_models import (
    DecisionProviderError,
    DecisionRequestError,
    call_decision_model,
    load_decision_credential,
)
from app.services.encryption import decrypt_config
from app.services.llm_trace import LLMTraceContext

# The routing state is sent to the decision model on every new turn, so it is
# truncated rather than unbounded. Platform limits are constants, not settings.
ROUTER_STATE_SYSTEM_CHARS = 2000
ROUTER_STATE_MESSAGE_CHARS = 4000
ROUTER_STATE_MAX_TOOLS = 40
DEFAULT_ROUTER_TIMEOUT_SECONDS = 10.0
ROUTING_QUESTION_ID = "route"

DEFAULT_ROUTING_INSTRUCTIONS = (
    "Choose the model best suited to this request. Read each option's criteria and "
    "pick the one whose criteria the request matches. When several fit, prefer the "
    "cheaper option."
)


class ModelRouterConfigError(ValueError):
    """Raised when a router credential's configuration cannot be used."""


class ModelRouterError(RuntimeError):
    """Raised when routing fails and there is no default option to fall back to."""


def _text(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class RouterOption:
    """One routable target: an LLM credential, a model on it, and when to use it."""

    id: str
    label: str
    credential_id: str
    model: str
    criteria: str
    is_default: bool = False


@dataclass(frozen=True)
class RouterConfig:
    """A parsed, validated router credential config."""

    decision_credential_id: str
    decision_model: str
    routing_instructions: str
    options: tuple[RouterOption, ...]
    timeout_seconds: float

    @property
    def default_option(self) -> RouterOption | None:
        """The option to use when the decision model cannot be consulted."""
        for option in self.options:
            if option.is_default:
                return option
        return None

    def option_by_label(self, label: str) -> RouterOption | None:
        """Resolve a label the decision model returned back to an option."""
        wanted = _text(label)
        if not wanted:
            return None
        for option in self.options:
            if option.label == wanted:
                return option
        lowered = wanted.lower()
        for option in self.options:
            if option.label.lower() == lowered:
                return option
        return None

    def fingerprint(self) -> str:
        """Stable digest of the routable surface, for decision reuse across turns."""
        payload = [
            [option.label, option.criteria, option.credential_id, option.model]
            for option in self.options
        ]
        payload.append([self.decision_model, self.routing_instructions])
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()


def _parse_option(raw: object, index: int) -> RouterOption:
    if not isinstance(raw, dict):
        raise ModelRouterConfigError(f"Model option {index + 1} is malformed")
    label = _text(raw.get("label"))
    if not label:
        raise ModelRouterConfigError(f"Model option {index + 1} needs a name")
    credential_id = _text(raw.get("credential_id"))
    if not credential_id:
        raise ModelRouterConfigError(f"Model option '{label}' needs a credential")
    model = _text(raw.get("model"))
    if not model:
        raise ModelRouterConfigError(f"Model option '{label}' needs a model")
    return RouterOption(
        id=_text(raw.get("id")) or f"opt_{index + 1}",
        label=label,
        credential_id=credential_id,
        model=model,
        criteria=_text(raw.get("criteria")),
        is_default=bool(raw.get("is_default")),
    )


def parse_router_config(config: dict) -> RouterConfig:
    """Validate a router credential's stored config and return it typed.

    Raises ModelRouterConfigError with a message meant for the user.
    """
    decision_credential_id = _text(config.get("decision_credential_id"))
    if not decision_credential_id:
        raise ModelRouterConfigError("Model Router needs a decision model credential")
    decision_model = _text(config.get("decision_model"))
    if not decision_model:
        raise ModelRouterConfigError("Model Router needs a decision model")

    raw_options = config.get("options")
    if not isinstance(raw_options, list):
        raise ModelRouterConfigError("Model Router options are malformed")
    options = tuple(_parse_option(raw, index) for index, raw in enumerate(raw_options))
    if len(options) < 2:
        raise ModelRouterConfigError(
            "Model Router needs at least two model options; with one there is nothing to route"
        )

    seen: set[str] = set()
    for option in options:
        lowered = option.label.lower()
        if lowered in seen:
            raise ModelRouterConfigError(
                f"Two model options share the same name '{option.label}'; "
                "names are what the decision model picks between"
            )
        seen.add(lowered)

    if sum(1 for option in options if option.is_default) > 1:
        raise ModelRouterConfigError("Only one option can be the fallback used when routing fails")

    raw_timeout = config.get("timeout_seconds")
    try:
        timeout_seconds = float(raw_timeout) if raw_timeout else DEFAULT_ROUTER_TIMEOUT_SECONDS
    except (TypeError, ValueError) as exc:
        raise ModelRouterConfigError("Model Router timeout must be a number") from exc
    if timeout_seconds <= 0:
        raise ModelRouterConfigError("Model Router timeout must be greater than zero")

    return RouterConfig(
        decision_credential_id=decision_credential_id,
        decision_model=decision_model,
        routing_instructions=_text(config.get("routing_instructions"))
        or DEFAULT_ROUTING_INSTRUCTIONS,
        options=options,
        timeout_seconds=timeout_seconds,
    )


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "…[truncated]"


def build_routing_state(
    *,
    system_instruction: str | None,
    message: str | None,
    tool_names: list[str] | None,
) -> dict[str, object]:
    """Describe the request to the decision model, bounded in size.

    Only what a routing decision needs travels: the system instruction, the current
    message and the names of the attached tools. Tool schemas never go, and neither
    does conversation history.
    """
    state: dict[str, object] = {}
    system = _text(system_instruction)
    if system:
        state["system"] = _truncate(system, ROUTER_STATE_SYSTEM_CHARS)
    body = _text(message)
    if body:
        state["message"] = _truncate(body, ROUTER_STATE_MESSAGE_CHARS)
    names = [_text(name) for name in (tool_names or []) if _text(name)]
    if names:
        state["tools"] = names[:ROUTER_STATE_MAX_TOOLS]
    return state


def state_hash(state: dict[str, object]) -> str:
    """Digest of a routing state, used to reuse a decision across identical turns."""
    return hashlib.sha256(
        json.dumps(state, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def build_routing_body(config: RouterConfig, state: dict[str, object]) -> dict[str, object]:
    """Build the decision model request that picks one option.

    The option labels become the `choice` keys, which is why they are validated
    non-empty and unique: they are the vocabulary the decision model answers in.
    """
    criteria: dict[str, str | None] = {
        option.label: (option.criteria or None) for option in config.options
    }
    return {
        "model": config.decision_model,
        "state": state,
        "questions": {
            ROUTING_QUESTION_ID: {
                "type": "choice",
                "instructions": config.routing_instructions,
                "criteria": criteria,
            }
        },
    }


def read_route_answer(payload: object) -> str | None:
    """Pull the chosen option label out of a decision model response."""
    if not isinstance(payload, dict):
        return None
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        return None
    answer = answers.get(ROUTING_QUESTION_ID)
    if not isinstance(answer, dict):
        return None
    return _text(answer.get("choice")) or None


@dataclass(frozen=True)
class RouteDecision:
    """The option bound for one provider call, and how it was reached.

    `decision_ms` is what the decision model cost this call, so the routed request's
    own trace can show routing next to the model time instead of hiding it in a
    separate row. A reused decision costs nothing and says so.
    """

    option: RouterOption
    fallback: bool = False
    error: str | None = None
    decision_ms: float = 0.0
    trace_id: str | None = None
    reused: bool = False


class ModelRouter:
    """Runtime side of a router credential: ask the decision model, bind an option."""

    def __init__(
        self,
        *,
        credential_id: str,
        label: str,
        config: RouterConfig,
        trace_context: LLMTraceContext | None = None,
    ) -> None:
        self.credential_id = credential_id
        self.label = label
        self.config = config
        self.trace_context = trace_context
        self._cached_key: str | None = None
        self._cached_decision: RouteDecision | None = None

    def route(
        self,
        *,
        system_instruction: str | None,
        message: str | None,
        tool_names: list[str] | None,
    ) -> RouteDecision:
        """Pick the option for this request.

        The decision is reused when the routing state is byte-for-byte what it was on
        the previous call, so an agent tool loop only pays for a decision when the
        conversation has actually moved. A fallback decision is never cached: the next
        turn gets a fresh chance to reach the decision model.
        """
        state = build_routing_state(
            system_instruction=system_instruction,
            message=message,
            tool_names=tool_names,
        )
        key = f"{self.config.fingerprint()}:{state_hash(state)}"
        if self._cached_key == key and self._cached_decision is not None:
            # Reused, so this turn spent no decision time; saying so keeps the routed
            # trace honest about which turns actually paid for a decision.
            return replace(self._cached_decision, decision_ms=0.0, reused=True)

        decision = self._decide(state)
        if not decision.fallback:
            self._cached_key = key
            self._cached_decision = decision
        return decision

    def decision_trace_context(self) -> LLMTraceContext | None:
        """The context the decision call is traced under.

        The row is attributed to the decision credential, because that is what the
        call spends, with the router named alongside so the two group together.
        """
        if self.trace_context is None:
            return None
        try:
            decision_uuid = uuid.UUID(str(self.config.decision_credential_id))
            router_uuid = uuid.UUID(str(self.credential_id))
        except ValueError:
            return self.trace_context
        return replace(
            self.trace_context,
            credential_id=decision_uuid,
            router_credential_id=router_uuid,
            router_label=self.label,
        )

    def _decide(self, state: dict[str, object]) -> RouteDecision:
        context = self.decision_trace_context()
        started = time.monotonic()
        try:
            credential = load_decision_credential(self.config.decision_credential_id)
            payload = call_decision_model(
                base_url=credential["base_url"],
                api_key=credential["api_key"],
                body=build_routing_body(self.config, state),
                timeout=self.config.timeout_seconds,
                trace_context=context,
            )
        except (DecisionProviderError, DecisionRequestError, OSError) as exc:
            return self._fallback(str(exc), self._elapsed_ms(started), self._trace_id(context))

        elapsed_ms = self._elapsed_ms(started)
        trace_id = self._trace_id(context)
        label = read_route_answer(payload)
        if label is None:
            return self._fallback("Decision model returned no routing answer", elapsed_ms, trace_id)
        option = self.config.option_by_label(label)
        if option is None:
            return self._fallback(
                f"Decision model chose '{label}', which is not a model option",
                elapsed_ms,
                trace_id,
            )
        return RouteDecision(option=option, decision_ms=elapsed_ms, trace_id=trace_id)

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.monotonic() - started) * 1000, 2)

    @staticmethod
    def _trace_id(context: LLMTraceContext | None) -> str | None:
        """The row `call_decision_model` just wrote, so the UI can link to it."""
        if context is None or not context.trace_ids:
            return None
        return str(context.trace_ids[-1])

    def _fallback(
        self,
        reason: str,
        decision_ms: float = 0.0,
        trace_id: str | None = None,
    ) -> RouteDecision:
        default = self.config.default_option
        if default is None:
            raise ModelRouterError(
                f"Model Router could not pick a model and has no fallback option: {reason}"
            )
        return RouteDecision(
            option=default,
            fallback=True,
            error=reason,
            decision_ms=decision_ms,
            trace_id=trace_id,
        )


@dataclass(frozen=True)
class BoundOption:
    """An option resolved into the values `LLMService` needs to build a client."""

    option: RouterOption
    credential_type: str
    api_key: str
    base_url: str | None
    credential_name: str
    credential_uuid: uuid.UUID


ROUTABLE_CREDENTIAL_TYPES = ("openai", "google", "custom")


def load_option_credential(option: RouterOption) -> BoundOption:
    """Read and decrypt the credential behind one routable option.

    Access is not re-checked against the running user: using a router credential is
    itself the grant, exactly as using a shared OpenAI credential is. The check that
    the router's owner could reach this credential happens when the router is saved.
    """
    try:
        credential_uuid = uuid.UUID(str(option.credential_id))
    except ValueError as exc:
        raise ModelRouterError(
            f"Model option '{option.label}' has an invalid credential id"
        ) from exc

    with SessionLocal() as db:
        credential = db.get(Credential, credential_uuid)
        if credential is None:
            raise ModelRouterError(
                f"Model option '{option.label}' points at a credential that no longer exists"
            )
        credential_type = credential.type.value
        credential_name = credential.name
        config = decrypt_config(credential.encrypted_config)

    if credential_type == CredentialType.model_router.value:
        raise ModelRouterError(
            f"Model option '{option.label}' points at another Model Router, which is not allowed"
        )
    if credential_type not in ROUTABLE_CREDENTIAL_TYPES:
        raise ModelRouterError(
            f"Model option '{option.label}' points at a {credential_type} credential, "
            "which cannot serve model requests"
        )

    api_key = _text(config.get("api_key"))
    if not api_key:
        raise ModelRouterError(f"Model option '{option.label}' has a credential with no API key")

    return BoundOption(
        option=option,
        credential_type=credential_type,
        api_key=api_key,
        base_url=_text(config.get("base_url")) or None,
        credential_name=credential_name,
        credential_uuid=credential_uuid,
    )


def build_router_for_credential(
    *,
    credential_id: str,
    credential_name: str,
    credential_type: str,
    config: dict,
    trace_context: object | None = None,
) -> ModelRouter | None:
    """Return a router for a router credential, or None for anything else.

    Every caller that loads an LLM credential goes through this, so adding a new
    model-request surface means one call here rather than a new branch per surface.
    """
    if credential_type != CredentialType.model_router.value:
        return None
    return ModelRouter(
        credential_id=credential_id,
        label=credential_name,
        config=parse_router_config(config),
        trace_context=trace_context,
    )
