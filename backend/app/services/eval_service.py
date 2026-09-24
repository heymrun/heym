import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    LLM_CREDENTIAL_TYPES,
    CredentialType,
    EvalRun,
    EvalRunResult,
    EvalSuite,
    User,
)
from app.services.credential_access import get_accessible_credential
from app.services.decision_models import (
    DecisionProviderError,
    build_decision_body,
    call_decision_model,
)
from app.services.encryption import decrypt_config
from app.services.llm_provider import is_reasoning_model
from app.services.llm_service import execute_llm
from app.services.llm_trace import LLMTraceContext
from app.services.model_router import build_router_for_credential

logger = logging.getLogger(__name__)

MAX_RETRIES_503 = 3
RETRY_DELAY_BASE = 2.0


def _is_retryable_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "503" in msg
        or "too_many_requests_error" in msg
        or "queue_exceeded" in msg
        or "rate_limit" in msg
    )


async def _execute_llm_with_retry(**kwargs: object) -> dict:
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES_503):
        try:
            return await execute_llm(**kwargs)
        except Exception as e:
            last_exc = e
            if not _is_retryable_error(e) or attempt == MAX_RETRIES_503 - 1:
                raise
            delay = RETRY_DELAY_BASE * (2**attempt)
            logger.warning(
                "LLM call failed (attempt %s/%s), retrying in %.1fs: %s",
                attempt + 1,
                MAX_RETRIES_503,
                delay,
                str(e),
            )
            await asyncio.sleep(delay)
    raise last_exc or RuntimeError("Unexpected retry loop exit")


SCORING_EXACT_MATCH = "exact_match"
SCORING_CONTAINS = "contains"
SCORING_LLM_JUDGE = "llm_judge"

COMBINED_LLM_JUDGE_PROMPT = """Answer the question below following the system instruction. Then evaluate how well YOUR answer matches the EXPECTED reference (what we want the model to produce). We measure alignment with EXPECTED—not general correctness. If your answer diverges from EXPECTED, the prompt may need improvement.

QUESTION:
{input}

EXPECTED (reference we want the model to match):
{expected}

Provide your answer, then score 0-100 how well it aligns with EXPECTED:
- 100: Your answer matches EXPECTED in meaning, key points, and intent.
- 80-99: Mostly matches, minor omissions or wording differences.
- 50-79: Partially matches, some key points missing or divergent.
- 20-49: Mostly does not match EXPECTED.
- 0-19: Completely off from what EXPECTED describes.

Output ONLY valid JSON: {{"actual_answer": "<your full answer>", "score": <0-100>, "explanation": "<brief reason>"}}"""


def _score_exact_match(actual: str, expected: str) -> str:
    a = (actual or "").strip()
    e = (expected or "").strip()
    return "100" if a == e else "0"


def _score_contains(actual: str, expected: str) -> str:
    a = actual or ""
    e = (expected or "").strip()
    if not e:
        return "100"
    return "100" if e in a else "0"


def _find_judge_payload(text: str) -> dict | None:
    """Find the JSON object a judge answered with.

    Handles what models actually send back: plain JSON, JSON fenced in markdown, and
    the object nested under a "response" or "output" key.
    """
    t = (text or "").strip()
    # Strip markdown code blocks (```json ... ``` or ``` ... ```)
    if "```" in t:
        for marker in ("```json", "```"):
            if marker in t:
                parts = t.split(marker, 2)
                if len(parts) >= 2:
                    # Content between marker and next ```
                    block = parts[1].split("```")[0].strip()
                    if block:
                        t = block
                    break

    start = t.find("{")
    if start < 0:
        return None
    depth = 0
    for i, c in enumerate(t[start:], start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(t[start : i + 1])
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
                if isinstance(data, dict):
                    inner = data.get("response") or data.get("output") or data
                    if isinstance(inner, dict):
                        return inner
    return None


def _parse_combined_judge_response(text: str) -> tuple[str, str, str | None]:
    """Parse JSON from combined judge response. Returns (actual_answer, score_str, explanation).

    Accepts "answer" in place of "actual_answer", and scores anything unreadable as 0.
    """
    inner = _find_judge_payload(text)
    if inner is None:
        return "", "0", None
    actual = str(inner.get("actual_answer", "") or inner.get("answer", "")).strip() or ""
    try:
        score = max(0, min(100, int(inner.get("score", 0))))
    except (ValueError, TypeError):
        score = 0
    explanation = str(inner.get("explanation", "")).strip() or None
    return actual, str(score), explanation


JUDGE_QUESTION_ID = "match"
JUDGE_REQUEST_TIMEOUT_SECONDS = 60.0
RETRYABLE_JUDGE_STATUS_CODES = frozenset({429, 503, 529})

# A judge is a model that writes its verdict or a decision model that computes one. A
# Model Router is left out: a judge that changes per request cannot be compared across runs.
JUDGE_CREDENTIAL_TYPES = (
    CredentialType.openai,
    CredentialType.google,
    CredentialType.custom,
    CredentialType.decision,
)

# Lowest first, as the score primitive requires. Each level names its situation in
# full because the decision model reads the text, not the position.
JUDGE_LEVELS: tuple[tuple[str, str], ...] = (
    ("Completely off", "The actual answer has nothing in common with the expected answer."),
    (
        "Mostly different",
        "Most key points of the expected answer are missing from the actual answer "
        "or contradicted by it.",
    ),
    (
        "Partially matches",
        "The actual answer shares some key points with the expected answer but misses "
        "or changes others.",
    ),
    (
        "Mostly matches",
        "The actual answer carries the meaning and key points of the expected answer, "
        "with minor omissions or wording differences.",
    ),
    (
        "Fully matches",
        "The actual answer has the same meaning, key points and intent as the expected answer.",
    ),
)

JUDGE_INSTRUCTIONS = (
    "The state holds a question, the expected_answer we want, and the actual_answer a "
    "model gave. How closely does actual_answer match expected_answer in meaning, key "
    "points and intent? Judge agreement with expected_answer only, not general quality "
    "or correctness, and do not count different wording as a mismatch."
)

LLM_JUDGE_SYSTEM_PROMPT = (
    "You are an impartial evaluator. You compare a model's answer with an expected "
    "reference answer and report how closely they agree."
)

LLM_JUDGE_PROMPT = """Score how well the ACTUAL answer matches the EXPECTED reference for the QUESTION. We measure alignment with EXPECTED, not general quality or correctness. Different wording alone is not a mismatch.

QUESTION:
{input}

EXPECTED:
{expected}

ACTUAL:
{actual}

Score 0-100:
- 100: ACTUAL matches EXPECTED in meaning, key points, and intent.
- 80-99: Mostly matches, minor omissions or wording differences.
- 50-79: Partially matches, some key points missing or divergent.
- 20-49: Mostly does not match EXPECTED.
- 0-19: Completely off from what EXPECTED describes.

Output ONLY valid JSON: {{"score": <0-100>, "explanation": "<brief reason>"}}"""


class EvalJudgeError(RuntimeError):
    """Raised when the judge cannot score an answer."""


@dataclass(frozen=True)
class EvalJudge:
    """A credential and model resolved for scoring LLM-as-Judge answers."""

    credential_id: UUID
    credential_type: CredentialType
    model: str
    base_url: str | None
    api_key: str = field(repr=False)

    @property
    def is_decision_model(self) -> bool:
        """True when the judge answers typed questions instead of writing its verdict."""
        return self.credential_type == CredentialType.decision


async def load_eval_judge(
    db: AsyncSession,
    *,
    credential_id: UUID | None,
    model: str | None,
    user_id: UUID,
) -> EvalJudge:
    """Resolve the judge a run asks for, or raise ValueError saying why it cannot be used."""
    resolved_model = (model or "").strip()
    if credential_id is None:
        raise ValueError("Choose a judge credential")
    if not resolved_model:
        raise ValueError("Enter the judge model")
    credential = await get_accessible_credential(
        db=db,
        credential_id=credential_id,
        user_id=user_id,
    )
    if not credential:
        raise ValueError("Judge credential not found")
    if credential.type not in JUDGE_CREDENTIAL_TYPES:
        raise ValueError(
            "Judge credential must be an OpenAI, Google, OpenAI-compatible or "
            "Decision Model credential"
        )
    config = decrypt_config(credential.encrypted_config)
    base_url: str | None = None
    if credential.type in (CredentialType.custom, CredentialType.decision):
        base_url = str(config.get("base_url") or "").strip() or None
        if base_url is None:
            raise ValueError("Judge credential has no base URL configured")
    return EvalJudge(
        credential_id=credential.id,
        credential_type=credential.type,
        model=resolved_model,
        base_url=base_url,
        api_key=str(config.get("api_key") or ""),
    )


def build_decision_judge_body(
    *, model: str, question: str, expected: str, actual: str
) -> dict[str, Any]:
    """Build the decision model request that scores one answer against the expected one."""
    return build_decision_body(
        model=model,
        state={
            "question": question,
            "expected_answer": (expected or "").strip() or "(none)",
            "actual_answer": actual,
        },
        questions=[
            {
                "id": JUDGE_QUESTION_ID,
                "type": "score",
                "instructions": JUDGE_INSTRUCTIONS,
                "levels": [f"{label}: {meaning}" for label, meaning in JUDGE_LEVELS],
            }
        ],
    )


def read_decision_judge_score(payload: object) -> tuple[str, str]:
    """Turn a decision model's answer into a 0-100 score and a readable explanation.

    A score answer is a probability-weighted position between the first and the last
    level, so it maps linearly onto the 0-100 scale every other scoring method uses.
    """
    answers = payload.get("answers") if isinstance(payload, dict) else None
    answer = answers.get(JUDGE_QUESTION_ID) if isinstance(answers, dict) else None
    value = answer.get("score") if isinstance(answer, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EvalJudgeError("Judge failed: the decision model returned no score")
    top = len(JUDGE_LEVELS) - 1
    position = min(max(float(value), 0.0), float(top))
    detail = f"score {position:.2f} of {top}"
    confidence = answer.get("confidence") if isinstance(answer, dict) else None
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        detail += f", confidence {float(confidence):.2f}"
    label = JUDGE_LEVELS[round(position)][0]
    return str(round(position / top * 100)), f"{label} ({detail})"


def read_llm_judge_score(text: str) -> tuple[str, str | None]:
    """Pull the 0-100 score and the explanation out of an LLM judge's JSON verdict."""
    payload = _find_judge_payload(text)
    if payload is None:
        raise EvalJudgeError("Judge failed: the judge model returned no JSON verdict")
    value = payload.get("score")
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            value = None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EvalJudgeError("Judge failed: the judge model returned no score")
    explanation = str(payload.get("explanation") or "").strip() or None
    return str(round(min(max(float(value), 0.0), 100.0))), explanation


async def _judge_with_decision_model(
    judge: EvalJudge,
    *,
    question: str,
    expected: str,
    actual: str,
    trace_context: LLMTraceContext | None,
) -> tuple[str, str]:
    """Score one answer with a decision model, retrying rate limits and overloads."""
    body = build_decision_judge_body(
        model=judge.model, question=question, expected=expected, actual=actual
    )
    attempt = 0
    while True:
        try:
            # The transport is synchronous, so it runs off the event loop.
            payload = await asyncio.to_thread(
                call_decision_model,
                base_url=judge.base_url or "",
                api_key=judge.api_key,
                body=body,
                timeout=JUDGE_REQUEST_TIMEOUT_SECONDS,
                trace_context=trace_context,
            )
            break
        except DecisionProviderError as exc:
            attempt += 1
            if exc.status_code not in RETRYABLE_JUDGE_STATUS_CODES:
                raise EvalJudgeError(f"Judge failed: {exc}") from exc
            if attempt >= MAX_RETRIES_503:
                raise EvalJudgeError(
                    f"Judge failed: the decision model stayed unavailable "
                    f"({exc.status_code}) after {attempt} attempts"
                ) from exc
            delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
            logger.warning(
                "Eval judge call failed (attempt %s/%s), retrying in %.1fs: %s",
                attempt,
                MAX_RETRIES_503,
                delay,
                str(exc),
            )
            await asyncio.sleep(delay)
        except (ValueError, OSError) as exc:
            # A blocked private address fails the same way on every attempt.
            raise EvalJudgeError(f"Judge failed: {exc}") from exc
    return read_decision_judge_score(payload)


async def _judge_with_llm(
    judge: EvalJudge,
    *,
    question: str,
    expected: str,
    actual: str,
    trace_context: LLMTraceContext | None,
) -> tuple[str, str | None]:
    """Score one answer with a separate model that writes a JSON verdict."""
    llm_kwargs: dict = {
        "credential_type": judge.credential_type.value,
        "api_key": judge.api_key,
        "base_url": judge.base_url,
        "model": judge.model,
        "system_instruction": LLM_JUDGE_SYSTEM_PROMPT,
        "user_message": LLM_JUDGE_PROMPT.format(
            input=question,
            expected=(expected or "").strip() or "(none)",
            actual=actual,
        ),
        "response_format": {"type": "json_object"},
        "content_only": True,
        "trace_context": trace_context,
    }
    # A judge should give the same verdict twice, so it runs without sampling noise.
    if is_reasoning_model(judge.model):
        llm_kwargs["reasoning_effort"] = "low"
    else:
        llm_kwargs["temperature"] = 0.0
    try:
        result = await _execute_llm_with_retry(**llm_kwargs)
    except Exception as exc:
        raise EvalJudgeError(f"Judge failed: {exc}") from exc
    return read_llm_judge_score(str(result.get("text") or ""))


async def judge_answer(
    judge: EvalJudge,
    *,
    question: str,
    expected: str,
    actual: str,
    trace_context: LLMTraceContext | None = None,
) -> tuple[str, str | None]:
    """Score one answer against the expected output with the run's judge."""
    if judge.is_decision_model:
        return await _judge_with_decision_model(
            judge, question=question, expected=expected, actual=actual, trace_context=trace_context
        )
    return await _judge_with_llm(
        judge, question=question, expected=expected, actual=actual, trace_context=trace_context
    )


async def create_run(
    db: AsyncSession,
    suite_id: UUID,
    credential_id: UUID,
    models: list[str],
    scoring_method: str,
    temperature: float,
    reasoning_effort: str | None,
    max_tokens: int | None,
    runs_per_test: int,
    judge_credential_id: UUID | None,
    judge_model: str | None,
    current_user: User,
) -> EvalRun:
    suite_result = await db.execute(
        select(EvalSuite)
        .where(EvalSuite.id == suite_id, EvalSuite.owner_id == current_user.id)
        .options(selectinload(EvalSuite.test_cases))
    )
    suite = suite_result.scalar_one_or_none()
    if not suite:
        raise ValueError("Suite not found")

    credential = await get_accessible_credential(
        db=db,
        credential_id=credential_id,
        user_id=current_user.id,
    )
    if not credential:
        raise ValueError("Credential not found")
    if credential.type not in LLM_CREDENTIAL_TYPES:
        raise ValueError("Credential must be OpenAI, Google, or Custom type")

    # LLM-as-Judge scores with a separate judge (a model or a decision model) when one
    # is given; without one, each model scores its own answer in a single request.
    judge: EvalJudge | None = None
    if scoring_method == SCORING_LLM_JUDGE and (
        judge_credential_id is not None or (judge_model or "").strip()
    ):
        judge = await load_eval_judge(
            db,
            credential_id=judge_credential_id,
            model=judge_model,
            user_id=current_user.id,
        )

    count_result = await db.execute(select(EvalRun).where(EvalRun.suite_id == suite_id))
    run_number = len(count_result.scalars().all()) + 1
    now = datetime.now(timezone.utc)
    run_name = f"Run #{run_number} — {now.strftime('%Y-%m-%d %H:%M')}"

    run = EvalRun(
        suite_id=suite_id,
        name=run_name,
        system_prompt_snapshot=suite.system_prompt,
        models=models,
        scoring_method=scoring_method,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
        judge_credential_id=judge.credential_id if judge else None,
        judge_model=judge.model if judge else None,
        status="running",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def execute_evals_for_run(
    run_id: UUID,
    credential_id: UUID,
    models: list[str],
    scoring_method: str,
    temperature: float,
    reasoning_effort: str | None,
    max_tokens: int | None,
    runs_per_test: int,
    user_id: UUID,
) -> None:
    """Run a created eval in the background; the judge is read from the run row."""
    from app.db.session import async_session_maker

    async with async_session_maker() as db:
        try:
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                return
            run_result = await db.execute(select(EvalRun).where(EvalRun.id == run_id))
            run = run_result.scalar_one_or_none()
            if not run:
                return
            await _run_evals_into_run(
                db=db,
                run=run,
                credential_id=credential_id,
                models=models,
                scoring_method=scoring_method,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                max_tokens=max_tokens,
                runs_per_test=runs_per_test,
                current_user=user,
            )
        except Exception:
            logger.exception("Background eval run failed for run_id=%s", run_id)
            run_result = await db.execute(select(EvalRun).where(EvalRun.id == run_id))
            run = run_result.scalar_one_or_none()
            if run:
                run.status = "failed"
                await db.commit()


async def _run_evals_into_run(
    db: AsyncSession,
    run: EvalRun,
    credential_id: UUID,
    models: list[str],
    scoring_method: str,
    temperature: float,
    reasoning_effort: str | None,
    max_tokens: int | None,
    runs_per_test: int,
    current_user: User,
) -> None:
    suite_result = await db.execute(
        select(EvalSuite)
        .where(EvalSuite.id == run.suite_id)
        .options(selectinload(EvalSuite.test_cases))
    )
    suite = suite_result.scalar_one_or_none()
    if not suite:
        return

    credential = await get_accessible_credential(
        db=db,
        credential_id=credential_id,
        user_id=current_user.id,
    )
    if not credential:
        raise ValueError("Credential not found")

    config = decrypt_config(credential.encrypted_config)
    router = build_router_for_credential(
        credential_id=str(credential.id),
        credential_name=credential.name,
        credential_type=credential.type.value,
        config=config,
    )
    api_key = config.get("api_key", "")
    base_url = config.get("base_url") if credential.type == CredentialType.custom else None

    # The run row is what history shows, so it is also what decides the judge. A judge
    # that went missing after the run was created fails the run rather than silently
    # falling back to self-scoring.
    judge: EvalJudge | None = None
    if scoring_method == SCORING_LLM_JUDGE and (
        run.judge_credential_id is not None or run.judge_model
    ):
        judge = await load_eval_judge(
            db,
            credential_id=run.judge_credential_id,
            model=run.judge_model,
            user_id=current_user.id,
        )

    semaphore = asyncio.Semaphore(3)
    db_lock = asyncio.Lock()

    from app.db.models import EvalTestCase

    async def generate_answer(
        tc: EvalTestCase,
        model_id: str,
        trace_context: LLMTraceContext,
    ) -> tuple[str, int | None]:
        """Ask the model under test for its plain answer to one test input."""
        llm_kwargs: dict = {
            "credential_type": credential.type.value,
            "api_key": api_key,
            "base_url": base_url,
            "model": model_id,
            "system_instruction": suite.system_prompt,
            "user_message": tc.input,
            "max_tokens": max_tokens,
            "trace_context": trace_context,
            "router": router,
        }
        if is_reasoning_model(model_id):
            llm_kwargs["reasoning_effort"] = reasoning_effort or "medium"
        else:
            llm_kwargs["temperature"] = temperature
        result = await _execute_llm_with_retry(**llm_kwargs)
        usage = result.get("usage", {})
        return result.get("text", ""), usage.get("total_tokens")

    async def process_one(
        tc: EvalTestCase,
        model_id: str,
        run_idx: int,
        run_order: int,
    ) -> None:
        actual_output = ""
        latency_ms = None
        tokens_used = None
        error_msg = None
        score = "0"
        explanation: str | None = None
        try:
            async with semaphore:
                start = time.time()
                run_trace_ctx = LLMTraceContext(
                    user_id=current_user.id,
                    credential_id=credential_id,
                    source="evals",
                    node_label="run_evals",
                )
                if scoring_method == SCORING_LLM_JUDGE and judge is None:
                    combined_prompt = COMBINED_LLM_JUDGE_PROMPT.format(
                        input=tc.input,
                        expected=tc.expected_output or "(none)",
                    )
                    llm_kwargs: dict = {
                        "credential_type": credential.type.value,
                        "api_key": api_key,
                        "base_url": base_url,
                        "model": model_id,
                        "system_instruction": suite.system_prompt,
                        "user_message": combined_prompt,
                        "max_tokens": max_tokens,
                        "response_format": {"type": "json_object"},
                        "content_only": True,
                        "trace_context": run_trace_ctx,
                        "router": router,
                    }
                    if is_reasoning_model(model_id):
                        llm_kwargs["reasoning_effort"] = "low"
                    else:
                        llm_kwargs["temperature"] = temperature
                        llm_kwargs["extra_body"] = {"disable_reasoning": True}
                    result = await _execute_llm_with_retry(**llm_kwargs)
                    text = (result.get("text") or "").strip()
                    actual_output, score, explanation = _parse_combined_judge_response(text)
                    elapsed_ms = int((time.time() - start) * 1000)
                    usage = result.get("usage", {})
                    tokens_used = usage.get("total_tokens")
                    latency_ms = elapsed_ms
                else:
                    actual_output, tokens_used = await generate_answer(tc, model_id, run_trace_ctx)
                    # Latency and tokens describe the model under test, so the judge
                    # call below is kept out of both; it has its own trace row.
                    latency_ms = int((time.time() - start) * 1000)
                    if judge is not None:
                        score, explanation = await judge_answer(
                            judge,
                            question=tc.input,
                            expected=tc.expected_output,
                            actual=actual_output,
                            trace_context=LLMTraceContext(
                                user_id=current_user.id,
                                credential_id=judge.credential_id,
                                source="evals",
                                node_label="eval_judge",
                                # One session per run keeps an OpenCode judge's cache warm.
                                session_id=str(run.id),
                            ),
                        )
                    elif scoring_method == SCORING_CONTAINS:
                        score = _score_contains(actual_output, tc.expected_output)
                    else:
                        score = _score_exact_match(actual_output, tc.expected_output)
        except Exception as e:
            error_msg = str(e)
            logger.exception(
                "Eval run failed for test case %s model %s run %s",
                tc.id,
                model_id,
                run_idx,
            )

        result_row = EvalRunResult(
            run_id=run.id,
            test_case_id=tc.id,
            model_id=model_id,
            input_snapshot=tc.input,
            expected_output_snapshot=tc.expected_output,
            actual_output=actual_output,
            score=score,
            explanation=explanation,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            error=error_msg,
            run_order=run_order,
        )
        async with db_lock:
            db.add(result_row)
            await db.commit()

    run_order = 0
    tasks = []
    for tc in suite.test_cases:
        for model_id in models:
            for run_idx in range(runs_per_test):
                tasks.append(process_one(tc, model_id, run_idx, run_order))
                run_order += 1
    await asyncio.gather(*tasks)

    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(run)
    return run


async def optimize_prompt(
    db: AsyncSession,
    credential_id: UUID,
    model: str,
    system_prompt: str,
    current_user: User,
) -> str:
    credential = await get_accessible_credential(
        db=db,
        credential_id=credential_id,
        user_id=current_user.id,
    )
    if not credential:
        raise ValueError("Credential not found")
    config = decrypt_config(credential.encrypted_config)
    router = build_router_for_credential(
        credential_id=str(credential.id),
        credential_name=credential.name,
        credential_type=credential.type.value,
        config=config,
    )
    api_key = config.get("api_key", "")
    base_url = config.get("base_url") if credential.type == CredentialType.custom else None

    optimize_system = """You are an expert prompt engineer. Improve the following system prompt for clarity, effectiveness, and completeness.
Return ONLY the improved prompt, no explanations or meta-commentary. Preserve the original intent and structure."""

    trace_ctx = LLMTraceContext(
        user_id=current_user.id,
        credential_id=credential_id,
        source="evals",
        node_label="optimize_prompt",
    )
    result = await execute_llm(
        credential_type=credential.type.value,
        api_key=api_key,
        base_url=base_url,
        model=model,
        system_instruction=optimize_system,
        user_message=system_prompt,
        temperature=0.3,
        max_tokens=4000,
        trace_context=trace_ctx,
        router=router,
    )
    return result.get("text", system_prompt)


async def generate_test_data(
    db: AsyncSession,
    credential_id: UUID,
    model: str,
    system_prompt: str,
    count: int,
    current_user: User,
) -> list[dict]:
    credential = await get_accessible_credential(
        db=db,
        credential_id=credential_id,
        user_id=current_user.id,
    )
    if not credential:
        raise ValueError("Credential not found")
    config = decrypt_config(credential.encrypted_config)
    router = build_router_for_credential(
        credential_id=str(credential.id),
        credential_name=credential.name,
        credential_type=credential.type.value,
        config=config,
    )
    api_key = config.get("api_key", "")
    base_url = config.get("base_url") if credential.type == CredentialType.custom else None

    prompt = f"""Given this system prompt, generate {count} diverse test cases. Each test case has:
1. input: A user message that would be sent to the system
2. expected_output: The ideal response from the system

System prompt:
---
{system_prompt}
---

Respond with a JSON array of objects, each with "input" and "expected_output" keys. No other text."""

    trace_ctx = LLMTraceContext(
        user_id=current_user.id,
        credential_id=credential_id,
        source="evals",
        node_label="generate_test_data",
    )
    result = await execute_llm(
        credential_type=credential.type.value,
        api_key=api_key,
        base_url=base_url,
        model=model,
        system_instruction=None,
        user_message=prompt,
        temperature=0.7,
        max_tokens=16000,
        trace_context=trace_ctx,
        router=router,
    )
    text = result.get("text", "[]")
    try:
        if "```" in text:
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                text = text[start:end]
        data = json.loads(text)
        if not isinstance(data, list):
            return []
        out = []
        for i, item in enumerate(data[:count]):
            if isinstance(item, dict):
                out.append(
                    {
                        "input": str(item.get("input", "")),
                        "expected_output": str(item.get("expected_output", "")),
                        "input_mode": "text",
                        "expected_mode": "text",
                        "order_index": i,
                    }
                )
        return out
    except json.JSONDecodeError:
        return []
