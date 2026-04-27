import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    CredentialType,
    EvalRun,
    EvalRunResult,
    EvalSuite,
    User,
)
from app.services.credential_access import get_accessible_credential
from app.services.encryption import decrypt_config
from app.services.llm_provider import is_reasoning_model
from app.services.llm_service import execute_llm
from app.services.llm_trace import LLMTraceContext

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


def _parse_combined_judge_response(text: str) -> tuple[str, str, str | None]:
    """Parse JSON from combined judge response. Returns (actual_answer, score_str, explanation).

    Handles various formats from reasoning models:
    - Plain JSON: {"actual_answer": "...", "score": N, "explanation": "..."}
    - Wrapped in markdown: ```json {...} ```
    - Nested: {"response": {"actual_answer": "...", ...}} or {"output": {...}}
    - Alternative keys: "answer" instead of "actual_answer"
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

    def _extract_from_data(data: dict) -> tuple[str, str, str | None] | None:
        """Extract actual_answer, score, explanation from dict, supporting nested structures."""
        # Flatten nested response/output wrapper
        inner = data.get("response") or data.get("output") or data
        if isinstance(inner, dict):
            actual = str(inner.get("actual_answer", "") or inner.get("answer", "")).strip() or ""
            try:
                score_val = inner.get("score", 0)
                score = max(0, min(100, int(score_val)))
            except (ValueError, TypeError):
                score = 0
            explanation = str(inner.get("explanation", "")).strip() or None
            return actual, str(score), explanation
        return None

    start = t.find("{")
    if start >= 0:
        depth = 0
        for i, c in enumerate(t[start:], start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(t[start : i + 1])
                        if isinstance(data, dict):
                            result = _extract_from_data(data)
                            if result:
                                return result
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass
    return "", "0", None


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
    if credential.type not in (CredentialType.openai, CredentialType.google, CredentialType.custom):
        raise ValueError("Credential must be OpenAI, Google, or Custom type")

    # LLM-as-Judge uses combined single-request flow with main model; judge credential optional

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
    judge_credential_id: UUID | None,
    judge_model: str | None,
    user_id: UUID,
) -> None:
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
                judge_credential_id=judge_credential_id,
                judge_model=judge_model,
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
    judge_credential_id: UUID | None,
    judge_model: str | None,
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
    api_key = config.get("api_key", "")
    base_url = config.get("base_url") if credential.type == CredentialType.custom else None

    semaphore = asyncio.Semaphore(3)
    db_lock = asyncio.Lock()

    from app.db.models import EvalTestCase

    async def process_one(
        tc: EvalTestCase,
        model_id: str,
        run_idx: int,
        run_order: int,
    ) -> None:
        nonlocal suite, credential, scoring_method, temperature, reasoning_effort, max_tokens
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
                if scoring_method == SCORING_LLM_JUDGE:
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
                    llm_kwargs: dict = {
                        "credential_type": credential.type.value,
                        "api_key": api_key,
                        "base_url": base_url,
                        "model": model_id,
                        "system_instruction": suite.system_prompt,
                        "user_message": tc.input,
                        "max_tokens": max_tokens,
                        "trace_context": run_trace_ctx,
                    }
                    if is_reasoning_model(model_id):
                        llm_kwargs["reasoning_effort"] = reasoning_effort or "medium"
                    else:
                        llm_kwargs["temperature"] = temperature
                    result = await _execute_llm_with_retry(**llm_kwargs)
                    actual_output = result.get("text", "")
                    if scoring_method == SCORING_CONTAINS:
                        score = _score_contains(actual_output, tc.expected_output)
                    else:
                        score = _score_exact_match(actual_output, tc.expected_output)
                    elapsed_ms = int((time.time() - start) * 1000)
                    usage = result.get("usage", {})
                    tokens_used = usage.get("total_tokens")
                    latency_ms = elapsed_ms
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
