"""LLM-as-Judge scoring in Evals with a separate judge: a model or a Decision Model."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import BackgroundTasks, HTTPException

from app.api import evals as evals_api
from app.db.models import CredentialType, EvalRun, EvalRunResult
from app.models.eval_schemas import RunEvalsRequest
from app.services import eval_service
from app.services.decision_models import DecisionProviderError
from app.services.eval_service import (
    JUDGE_LEVELS,
    JUDGE_QUESTION_ID,
    EvalJudge,
    EvalJudgeError,
    _parse_combined_judge_response,
    build_decision_judge_body,
    judge_answer,
    load_eval_judge,
    read_decision_judge_score,
    read_llm_judge_score,
)
from app.services.llm_trace import LLMTraceContext

MAIN_CREDENTIAL_ID = uuid.uuid4()
JUDGE_CREDENTIAL_ID = uuid.uuid4()


def _credential(
    credential_id: uuid.UUID, credential_type: CredentialType, secret_ref: str
) -> SimpleNamespace:
    return SimpleNamespace(
        id=credential_id,
        name=f"{credential_type.value} credential",
        type=credential_type,
        encrypted_config=secret_ref,
    )


CONFIGS = {
    "main": {"api_key": "sk-main"},
    "llm-judge": {"api_key": "sk-llm-judge"},
    "compatible-judge": {"api_key": "sk-compatible", "base_url": "https://llm.example.com/v1"},
    "compatible-no-url": {"api_key": "sk-compatible"},
    "decision-judge": {"base_url": "https://api.typesafe.ai", "api_key": "sk-decision"},
    "decision-no-url": {"api_key": "sk-decision"},
}


def _score_payload(score: float, confidence: float | None = 0.9) -> dict:
    answer: dict = {"type": "score", "score": score}
    if confidence is not None:
        answer["confidence"] = confidence
    return {"model": "jev-1.13.0", "answers": {JUDGE_QUESTION_ID: answer}}


def _decision_judge() -> EvalJudge:
    return EvalJudge(
        credential_id=JUDGE_CREDENTIAL_ID,
        credential_type=CredentialType.decision,
        model="jev-latest",
        base_url="https://api.typesafe.ai",
        api_key="sk-decision",
    )


def _llm_judge(model: str = "gpt-4o-mini") -> EvalJudge:
    return EvalJudge(
        credential_id=JUDGE_CREDENTIAL_ID,
        credential_type=CredentialType.openai,
        model=model,
        base_url=None,
        api_key="sk-llm-judge",
    )


class BuildDecisionJudgeBodyTests(unittest.TestCase):
    def test_the_answer_is_scored_on_an_ordered_rubric(self) -> None:
        body = build_decision_judge_body(
            model="jev-latest",
            question="Capital of France?",
            expected="Paris",
            actual="It is Paris.",
        )

        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(
            body["state"],
            {
                "question": "Capital of France?",
                "expected_answer": "Paris",
                "actual_answer": "It is Paris.",
            },
        )
        question = body["questions"][JUDGE_QUESTION_ID]
        self.assertEqual(question["type"], "score")
        self.assertEqual(len(question["criteria"]), len(JUDGE_LEVELS))
        self.assertTrue(question["criteria"][0].startswith("Completely off"))
        self.assertTrue(question["criteria"][-1].startswith("Fully matches"))

    def test_a_blank_expected_answer_is_spelled_out(self) -> None:
        body = build_decision_judge_body(
            model="jev-latest", question="q", expected="  ", actual="a"
        )
        self.assertEqual(body["state"]["expected_answer"], "(none)")


class ReadDecisionJudgeScoreTests(unittest.TestCase):
    def test_the_top_level_is_a_full_score(self) -> None:
        score, explanation = read_decision_judge_score(_score_payload(4.0))
        self.assertEqual(score, "100")
        self.assertTrue(explanation.startswith("Fully matches"))

    def test_the_bottom_level_is_zero(self) -> None:
        score, explanation = read_decision_judge_score(_score_payload(0.0))
        self.assertEqual(score, "0")
        self.assertTrue(explanation.startswith("Completely off"))

    def test_a_score_between_levels_maps_linearly(self) -> None:
        score, explanation = read_decision_judge_score(_score_payload(3.2, confidence=0.87))
        self.assertEqual(score, "80")
        self.assertEqual(explanation, "Mostly matches (score 3.20 of 4, confidence 0.87)")

    def test_confidence_is_optional(self) -> None:
        _, explanation = read_decision_judge_score(_score_payload(2.0, confidence=None))
        self.assertEqual(explanation, "Partially matches (score 2.00 of 4)")

    def test_an_out_of_range_score_is_clamped(self) -> None:
        self.assertEqual(read_decision_judge_score(_score_payload(7.5))[0], "100")
        self.assertEqual(read_decision_judge_score(_score_payload(-1.0))[0], "0")

    def test_a_missing_or_malformed_score_is_an_error(self) -> None:
        for payload in (
            {},
            {"answers": {}},
            {"answers": {JUDGE_QUESTION_ID: {"type": "score"}}},
            {"answers": {JUDGE_QUESTION_ID: {"score": "high"}}},
            {"answers": {JUDGE_QUESTION_ID: {"score": True}}},
            {"answers": {JUDGE_QUESTION_ID: {"score": float("nan")}}},
            None,
        ):
            with self.subTest(payload=payload), self.assertRaises(EvalJudgeError):
                read_decision_judge_score(payload)


class ReadLlmJudgeScoreTests(unittest.TestCase):
    def test_plain_json(self) -> None:
        self.assertEqual(
            read_llm_judge_score('{"score": 85, "explanation": "Close enough"}'),
            ("85", "Close enough"),
        )

    def test_fenced_and_nested_json(self) -> None:
        text = '```json\n{"response": {"score": "72.6", "explanation": " Misses a date "}}\n```'
        self.assertEqual(read_llm_judge_score(text), ("73", "Misses a date"))

    def test_the_score_is_clamped_and_the_explanation_is_optional(self) -> None:
        self.assertEqual(read_llm_judge_score('{"score": 140}'), ("100", None))
        self.assertEqual(read_llm_judge_score('{"score": -5}'), ("0", None))

    def test_an_unreadable_verdict_is_an_error_not_a_zero(self) -> None:
        for text in ("I think it matches.", '{"explanation": "no score"}', '{"score": "high"}'):
            with self.subTest(text=text), self.assertRaises(EvalJudgeError):
                read_llm_judge_score(text)


class CombinedJudgeParserTests(unittest.TestCase):
    """Self-scoring keeps its lenient parser: anything unreadable scores 0."""

    def test_fenced_nested_answer(self) -> None:
        text = '```json\n{"output": {"answer": "Paris", "score": 91.7, "explanation": "ok"}}\n```'
        self.assertEqual(_parse_combined_judge_response(text), ("Paris", "91", "ok"))

    def test_unreadable_text_scores_zero(self) -> None:
        self.assertEqual(_parse_combined_judge_response("no json here"), ("", "0", None))
        self.assertEqual(
            _parse_combined_judge_response('{"actual_answer": "x", "score": "high"}'),
            ("x", "0", None),
        )


class JudgeAnswerWithDecisionModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_decision_model_scores_the_answer(self) -> None:
        trace = LLMTraceContext(user_id=uuid.uuid4(), credential_id=JUDGE_CREDENTIAL_ID)
        with patch.object(
            eval_service, "call_decision_model", MagicMock(return_value=_score_payload(4.0))
        ) as call:
            score, _ = await judge_answer(
                _decision_judge(),
                question="Capital of France?",
                expected="Paris",
                actual="Paris",
                trace_context=trace,
            )

        self.assertEqual(score, "100")
        kwargs = call.call_args.kwargs
        self.assertEqual(kwargs["base_url"], "https://api.typesafe.ai")
        self.assertEqual(kwargs["api_key"], "sk-decision")
        self.assertEqual(kwargs["body"]["state"]["actual_answer"], "Paris")
        self.assertIs(kwargs["trace_context"], trace)

    async def test_a_rate_limit_is_retried(self) -> None:
        responses = [DecisionProviderError("slow down", status_code=429), _score_payload(3.0)]
        with (
            patch.object(eval_service, "call_decision_model", MagicMock(side_effect=responses)),
            patch.object(eval_service.asyncio, "sleep", AsyncMock()) as sleep,
        ):
            score, _ = await judge_answer(_decision_judge(), question="q", expected="e", actual="a")

        self.assertEqual(score, "75")
        sleep.assert_awaited_once()

    async def test_a_persistent_overload_gives_up_with_a_clear_message(self) -> None:
        error = DecisionProviderError("overloaded", status_code=529)
        with (
            patch.object(eval_service, "call_decision_model", MagicMock(side_effect=error)) as call,
            patch.object(eval_service.asyncio, "sleep", AsyncMock()),
            self.assertRaises(EvalJudgeError) as ctx,
        ):
            await judge_answer(_decision_judge(), question="q", expected="e", actual="a")

        self.assertEqual(call.call_count, eval_service.MAX_RETRIES_503)
        self.assertIn("stayed unavailable (529)", str(ctx.exception))

    async def test_a_rejected_key_is_not_retried(self) -> None:
        error = DecisionProviderError("Decision model rejected the API key", status_code=401)
        with (
            patch.object(eval_service, "call_decision_model", MagicMock(side_effect=error)) as call,
            self.assertRaises(EvalJudgeError) as ctx,
        ):
            await judge_answer(_decision_judge(), question="q", expected="e", actual="a")

        call.assert_called_once()
        self.assertEqual(str(ctx.exception), "Judge failed: Decision model rejected the API key")

    async def test_a_blocked_endpoint_is_not_retried(self) -> None:
        with (
            patch.object(
                eval_service,
                "call_decision_model",
                MagicMock(side_effect=ValueError("resolves to a non-public address")),
            ) as call,
            self.assertRaises(EvalJudgeError),
        ):
            await judge_answer(_decision_judge(), question="q", expected="e", actual="a")

        call.assert_called_once()


class JudgeAnswerWithLlmTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_separate_model_writes_the_verdict(self) -> None:
        trace = LLMTraceContext(user_id=uuid.uuid4(), credential_id=JUDGE_CREDENTIAL_ID)
        execute_llm = AsyncMock(return_value={"text": '{"score": 90, "explanation": "Same city"}'})
        with patch.object(eval_service, "execute_llm", execute_llm):
            score, explanation = await judge_answer(
                _llm_judge(),
                question="Capital of France?",
                expected="Paris",
                actual="It is Paris.",
                trace_context=trace,
            )

        self.assertEqual((score, explanation), ("90", "Same city"))
        kwargs = execute_llm.await_args.kwargs
        self.assertEqual(kwargs["credential_type"], "openai")
        self.assertEqual(kwargs["api_key"], "sk-llm-judge")
        self.assertEqual(kwargs["model"], "gpt-4o-mini")
        self.assertEqual(kwargs["system_instruction"], eval_service.LLM_JUDGE_SYSTEM_PROMPT)
        self.assertIn("QUESTION:\nCapital of France?", kwargs["user_message"])
        self.assertIn("EXPECTED:\nParis", kwargs["user_message"])
        self.assertIn("ACTUAL:\nIt is Paris.", kwargs["user_message"])
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(kwargs["temperature"], 0.0)
        self.assertNotIn("reasoning_effort", kwargs)
        self.assertIs(kwargs["trace_context"], trace)

    async def test_a_reasoning_judge_thinks_briefly_instead_of_cooling_down(self) -> None:
        execute_llm = AsyncMock(return_value={"text": '{"score": 40}'})
        with patch.object(eval_service, "execute_llm", execute_llm):
            await judge_answer(_llm_judge("o3-mini"), question="q", expected="e", actual="a")

        kwargs = execute_llm.await_args.kwargs
        self.assertEqual(kwargs["reasoning_effort"], "low")
        self.assertNotIn("temperature", kwargs)

    async def test_braces_in_the_answer_do_not_break_the_prompt(self) -> None:
        execute_llm = AsyncMock(return_value={"text": '{"score": 100}'})
        with patch.object(eval_service, "execute_llm", execute_llm):
            await judge_answer(_llm_judge(), question="{x}", expected='{"a": 1}', actual="{{}}")

        self.assertIn('EXPECTED:\n{"a": 1}', execute_llm.await_args.kwargs["user_message"])

    async def test_a_provider_failure_names_the_judge(self) -> None:
        execute_llm = AsyncMock(side_effect=RuntimeError("401 invalid api key"))
        with (
            patch.object(eval_service, "execute_llm", execute_llm),
            self.assertRaises(EvalJudgeError) as ctx,
        ):
            await judge_answer(_llm_judge(), question="q", expected="e", actual="a")

        self.assertEqual(str(ctx.exception), "Judge failed: 401 invalid api key")

    async def test_a_verdict_without_a_score_is_an_error(self) -> None:
        execute_llm = AsyncMock(return_value={"text": "Looks right to me."})
        with (
            patch.object(eval_service, "execute_llm", execute_llm),
            self.assertRaises(EvalJudgeError),
        ):
            await judge_answer(_llm_judge(), question="q", expected="e", actual="a")


class LoadEvalJudgeTests(unittest.IsolatedAsyncioTestCase):
    async def _load(
        self,
        credential: SimpleNamespace | None,
        *,
        credential_id: uuid.UUID | None = JUDGE_CREDENTIAL_ID,
        model: str | None = " jev-latest ",
    ) -> EvalJudge:
        with (
            patch.object(
                eval_service, "get_accessible_credential", AsyncMock(return_value=credential)
            ),
            patch.object(eval_service, "decrypt_config", side_effect=CONFIGS.__getitem__),
        ):
            return await load_eval_judge(
                AsyncMock(), credential_id=credential_id, model=model, user_id=uuid.uuid4()
            )

    async def test_a_decision_credential_becomes_a_judge(self) -> None:
        judge = await self._load(
            _credential(JUDGE_CREDENTIAL_ID, CredentialType.decision, "decision-judge")
        )

        self.assertTrue(judge.is_decision_model)
        self.assertEqual(judge.credential_id, JUDGE_CREDENTIAL_ID)
        self.assertEqual(judge.model, "jev-latest")
        self.assertEqual(judge.base_url, "https://api.typesafe.ai")
        self.assertEqual(judge.api_key, "sk-decision")
        self.assertNotIn("sk-decision", repr(judge))

    async def test_openai_and_google_credentials_can_judge(self) -> None:
        for credential_type in (CredentialType.openai, CredentialType.google):
            with self.subTest(credential_type=credential_type):
                judge = await self._load(
                    _credential(JUDGE_CREDENTIAL_ID, credential_type, "llm-judge"),
                    model="judge-model",
                )
                self.assertFalse(judge.is_decision_model)
                self.assertEqual(judge.credential_type, credential_type)
                self.assertIsNone(judge.base_url)

    async def test_an_openai_compatible_credential_brings_its_base_url(self) -> None:
        judge = await self._load(
            _credential(JUDGE_CREDENTIAL_ID, CredentialType.custom, "compatible-judge"),
            model="llama-3.3-70b",
        )
        self.assertEqual(judge.base_url, "https://llm.example.com/v1")

    async def test_a_model_router_cannot_judge(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be an OpenAI, Google"):
            await self._load(_credential(JUDGE_CREDENTIAL_ID, CredentialType.model_router, "main"))

    async def test_an_unrelated_credential_cannot_judge(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be an OpenAI, Google"):
            await self._load(_credential(JUDGE_CREDENTIAL_ID, CredentialType.github, "main"))

    async def test_an_inaccessible_credential_is_not_found(self) -> None:
        with self.assertRaisesRegex(ValueError, "not found"):
            await self._load(None)

    async def test_the_model_is_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "judge model"):
            await self._load(
                _credential(JUDGE_CREDENTIAL_ID, CredentialType.decision, "decision-judge"),
                model="  ",
            )

    async def test_the_credential_is_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "judge credential"):
            await self._load(None, credential_id=None)

    async def test_a_credential_without_its_base_url_is_rejected(self) -> None:
        for credential_type, secret_ref in (
            (CredentialType.decision, "decision-no-url"),
            (CredentialType.custom, "compatible-no-url"),
        ):
            with (
                self.subTest(credential_type=credential_type),
                self.assertRaisesRegex(ValueError, "base URL"),
            ):
                await self._load(_credential(JUDGE_CREDENTIAL_ID, credential_type, secret_ref))


def _credential_lookup(**credentials: SimpleNamespace) -> AsyncMock:
    by_id = {credential.id: credential for credential in credentials.values()}

    async def lookup(*, db: object, credential_id: uuid.UUID, user_id: uuid.UUID) -> object:
        return by_id.get(credential_id)

    return AsyncMock(side_effect=lookup)


class CreateRunTests(unittest.IsolatedAsyncioTestCase):
    async def _create(
        self,
        *,
        scoring_method: str,
        judge_credential: SimpleNamespace | None,
        judge_credential_id: uuid.UUID | None,
        judge_model: str | None,
    ) -> EvalRun:
        suite = SimpleNamespace(id=uuid.uuid4(), system_prompt="Answer briefly.", test_cases=[])
        count_result = MagicMock()
        count_result.scalars.return_value.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=suite)),
                count_result,
            ]
        )
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        credentials = {"main": _credential(MAIN_CREDENTIAL_ID, CredentialType.openai, "main")}
        if judge_credential is not None:
            credentials["judge"] = judge_credential
        with (
            patch.object(
                eval_service, "get_accessible_credential", _credential_lookup(**credentials)
            ),
            patch.object(eval_service, "decrypt_config", side_effect=CONFIGS.__getitem__),
        ):
            return await eval_service.create_run(
                db=db,
                suite_id=suite.id,
                credential_id=MAIN_CREDENTIAL_ID,
                models=["gpt-4o"],
                scoring_method=scoring_method,
                temperature=0.7,
                reasoning_effort=None,
                max_tokens=None,
                runs_per_test=1,
                judge_credential_id=judge_credential_id,
                judge_model=judge_model,
                current_user=SimpleNamespace(id=uuid.uuid4()),
            )

    async def test_a_decision_judge_is_recorded_on_the_run(self) -> None:
        run = await self._create(
            scoring_method="llm_judge",
            judge_credential=_credential(
                JUDGE_CREDENTIAL_ID, CredentialType.decision, "decision-judge"
            ),
            judge_credential_id=JUDGE_CREDENTIAL_ID,
            judge_model="  jev-latest ",
        )

        self.assertEqual(run.judge_credential_id, JUDGE_CREDENTIAL_ID)
        self.assertEqual(run.judge_model, "jev-latest")

    async def test_an_llm_judge_is_recorded_on_the_run(self) -> None:
        run = await self._create(
            scoring_method="llm_judge",
            judge_credential=_credential(JUDGE_CREDENTIAL_ID, CredentialType.google, "llm-judge"),
            judge_credential_id=JUDGE_CREDENTIAL_ID,
            judge_model="gemini-2.5-flash",
        )

        self.assertEqual(run.judge_credential_id, JUDGE_CREDENTIAL_ID)
        self.assertEqual(run.judge_model, "gemini-2.5-flash")

    async def test_a_self_scored_run_records_no_judge(self) -> None:
        run = await self._create(
            scoring_method="llm_judge",
            judge_credential=None,
            judge_credential_id=None,
            judge_model=None,
        )

        self.assertIsNone(run.judge_credential_id)
        self.assertIsNone(run.judge_model)

    async def test_other_scoring_methods_ignore_judge_fields(self) -> None:
        run = await self._create(
            scoring_method="exact_match",
            judge_credential=_credential(JUDGE_CREDENTIAL_ID, CredentialType.openai, "llm-judge"),
            judge_credential_id=JUDGE_CREDENTIAL_ID,
            judge_model="gpt-4o",
        )

        self.assertIsNone(run.judge_credential_id)
        self.assertIsNone(run.judge_model)

    async def test_a_model_router_is_refused_as_judge(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be an OpenAI, Google"):
            await self._create(
                scoring_method="llm_judge",
                judge_credential=_credential(
                    JUDGE_CREDENTIAL_ID, CredentialType.model_router, "main"
                ),
                judge_credential_id=JUDGE_CREDENTIAL_ID,
                judge_model="auto",
            )

    async def test_a_judge_model_without_a_credential_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "judge credential"):
            await self._create(
                scoring_method="llm_judge",
                judge_credential=None,
                judge_credential_id=None,
                judge_model="jev-latest",
            )


class RunEvalsIntoRunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.test_cases = [
            SimpleNamespace(id=uuid.uuid4(), input="Capital of France?", expected_output="Paris")
        ]
        self.suite = SimpleNamespace(
            id=uuid.uuid4(), system_prompt="Answer briefly.", test_cases=self.test_cases
        )
        self.db = MagicMock()
        self.db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=self.suite))
        )
        self.db.commit = AsyncMock()
        self.db.refresh = AsyncMock()
        self.execute_llm = AsyncMock(return_value={"text": "Paris.", "usage": {"total_tokens": 12}})
        self.call_decision_model = MagicMock(return_value=_score_payload(3.2, confidence=0.87))

    def _run(self, **fields: object) -> SimpleNamespace:
        values: dict = {
            "id": uuid.uuid4(),
            "suite_id": self.suite.id,
            "judge_credential_id": None,
            "judge_model": None,
            "status": "running",
            "completed_at": None,
        }
        values.update(fields)
        return SimpleNamespace(**values)

    async def _execute(
        self,
        run: SimpleNamespace,
        *,
        scoring_method: str,
        main_type: CredentialType = CredentialType.openai,
        judge_type: CredentialType = CredentialType.decision,
        router: object | None = None,
    ) -> list[EvalRunResult]:
        judge_ref = "decision-judge" if judge_type == CredentialType.decision else "llm-judge"
        credentials = {
            "main": _credential(MAIN_CREDENTIAL_ID, main_type, "main"),
            "judge": _credential(JUDGE_CREDENTIAL_ID, judge_type, judge_ref),
        }
        with (
            patch.object(
                eval_service, "get_accessible_credential", _credential_lookup(**credentials)
            ),
            patch.object(eval_service, "decrypt_config", side_effect=CONFIGS.__getitem__),
            patch.object(eval_service, "execute_llm", self.execute_llm),
            patch.object(eval_service, "call_decision_model", self.call_decision_model),
            patch.object(eval_service, "build_router_for_credential", return_value=router),
        ):
            await eval_service._run_evals_into_run(
                db=self.db,
                run=run,
                credential_id=MAIN_CREDENTIAL_ID,
                models=["gpt-4o"],
                scoring_method=scoring_method,
                temperature=0.7,
                reasoning_effort=None,
                max_tokens=None,
                runs_per_test=1,
                current_user=SimpleNamespace(id=uuid.uuid4()),
            )
        return [
            call.args[0]
            for call in self.db.add.call_args_list
            if isinstance(call.args[0], EvalRunResult)
        ]

    async def test_the_decision_model_scores_the_plain_answer(self) -> None:
        run = self._run(judge_credential_id=JUDGE_CREDENTIAL_ID, judge_model="jev-latest")

        rows = await self._execute(run, scoring_method="llm_judge")

        llm_kwargs = self.execute_llm.await_args.kwargs
        self.assertEqual(llm_kwargs["user_message"], "Capital of France?")
        self.assertEqual(llm_kwargs["system_instruction"], "Answer briefly.")
        self.assertNotIn("response_format", llm_kwargs)
        self.assertEqual(llm_kwargs["temperature"], 0.7)

        judge_kwargs = self.call_decision_model.call_args.kwargs
        self.assertEqual(judge_kwargs["body"]["model"], "jev-latest")
        self.assertEqual(
            judge_kwargs["body"]["state"],
            {
                "question": "Capital of France?",
                "expected_answer": "Paris",
                "actual_answer": "Paris.",
            },
        )
        trace = judge_kwargs["trace_context"]
        self.assertEqual(trace.credential_id, JUDGE_CREDENTIAL_ID)
        self.assertEqual(trace.source, "evals")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].actual_output, "Paris.")
        self.assertEqual(rows[0].score, "80")
        self.assertEqual(rows[0].explanation, "Mostly matches (score 3.20 of 4, confidence 0.87)")
        self.assertEqual(rows[0].tokens_used, 12)
        self.assertIsNone(rows[0].error)
        self.assertEqual(run.status, "completed")

    async def test_an_llm_judge_scores_the_answer_with_its_own_credential(self) -> None:
        self.execute_llm.side_effect = [
            {"text": "Paris.", "usage": {"total_tokens": 12}},
            {"text": '{"score": 95, "explanation": "Same city"}', "usage": {"total_tokens": 80}},
        ]
        run = self._run(judge_credential_id=JUDGE_CREDENTIAL_ID, judge_model="gemini-2.5-flash")

        rows = await self._execute(
            run, scoring_method="llm_judge", judge_type=CredentialType.google
        )

        answer_call, judge_call = self.execute_llm.await_args_list
        self.assertEqual(answer_call.kwargs["credential_type"], "openai")
        self.assertEqual(answer_call.kwargs["user_message"], "Capital of France?")
        self.assertEqual(judge_call.kwargs["credential_type"], "google")
        self.assertEqual(judge_call.kwargs["api_key"], "sk-llm-judge")
        self.assertEqual(judge_call.kwargs["model"], "gemini-2.5-flash")
        self.assertIn("ACTUAL:\nParis.", judge_call.kwargs["user_message"])
        self.assertEqual(judge_call.kwargs["trace_context"].credential_id, JUDGE_CREDENTIAL_ID)
        self.call_decision_model.assert_not_called()
        self.assertEqual((rows[0].score, rows[0].explanation), ("95", "Same city"))
        self.assertEqual(rows[0].tokens_used, 12)

    async def test_every_judge_call_in_a_run_shares_one_session(self) -> None:
        """OpenCode caches the judge prompt per session, so one run is one session."""
        self.test_cases.append(
            SimpleNamespace(id=uuid.uuid4(), input="Capital of Italy?", expected_output="Rome")
        )
        self.execute_llm.side_effect = None
        self.execute_llm.return_value = {"text": '{"score": 50}', "usage": {}}
        first = self._run(judge_credential_id=JUDGE_CREDENTIAL_ID, judge_model="gpt-4o-mini")
        await self._execute(first, scoring_method="llm_judge", judge_type=CredentialType.openai)
        first_sessions = {
            call.kwargs["trace_context"].session_id
            for call in self.execute_llm.await_args_list
            if call.kwargs["model"] == "gpt-4o-mini"
        }

        self.execute_llm.reset_mock()
        second = self._run(judge_credential_id=JUDGE_CREDENTIAL_ID, judge_model="gpt-4o-mini")
        await self._execute(second, scoring_method="llm_judge", judge_type=CredentialType.openai)
        second_sessions = {
            call.kwargs["trace_context"].session_id
            for call in self.execute_llm.await_args_list
            if call.kwargs["model"] == "gpt-4o-mini"
        }

        self.assertEqual(first_sessions, {str(first.id)})
        self.assertEqual(second_sessions, {str(second.id)})

    async def test_a_judge_failure_keeps_the_answer_and_names_the_judge(self) -> None:
        self.call_decision_model.side_effect = DecisionProviderError(
            "Decision model rejected the API key", status_code=401
        )
        run = self._run(judge_credential_id=JUDGE_CREDENTIAL_ID, judge_model="jev-latest")

        rows = await self._execute(run, scoring_method="llm_judge")

        self.assertEqual(rows[0].actual_output, "Paris.")
        self.assertEqual(rows[0].score, "0")
        self.assertEqual(rows[0].error, "Judge failed: Decision model rejected the API key")
        self.assertEqual(run.status, "completed")

    async def test_without_a_judge_each_model_scores_itself(self) -> None:
        self.execute_llm.return_value = {
            "text": '{"actual_answer": "Paris", "score": 90, "explanation": "close"}',
            "usage": {"total_tokens": 30},
        }

        rows = await self._execute(self._run(), scoring_method="llm_judge")

        llm_kwargs = self.execute_llm.await_args.kwargs
        self.assertIn("EXPECTED", llm_kwargs["user_message"])
        self.assertEqual(llm_kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(self.execute_llm.await_count, 1)
        self.call_decision_model.assert_not_called()
        self.assertEqual(rows[0].score, "90")
        self.assertEqual(rows[0].actual_output, "Paris")

    async def test_a_judge_that_went_missing_fails_the_run(self) -> None:
        # The credential was deleted after the run was created, so SET NULL cleared it.
        run = self._run(judge_credential_id=None, judge_model="jev-latest")

        with self.assertRaisesRegex(ValueError, "judge credential"):
            await self._execute(run, scoring_method="llm_judge")

        self.execute_llm.assert_not_awaited()

    async def test_exact_match_never_calls_the_judge(self) -> None:
        run = self._run(judge_credential_id=JUDGE_CREDENTIAL_ID, judge_model="jev-latest")

        rows = await self._execute(run, scoring_method="exact_match")

        self.call_decision_model.assert_not_called()
        self.assertEqual(self.execute_llm.await_count, 1)
        self.assertEqual(rows[0].score, "0")

    async def test_an_auto_model_credential_is_routed_for_plain_answers(self) -> None:
        router = object()

        await self._execute(
            self._run(),
            scoring_method="contains",
            main_type=CredentialType.model_router,
            router=router,
        )

        self.assertIs(self.execute_llm.await_args.kwargs["router"], router)


def _stored_run(**fields: object) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    values: dict = {
        "id": uuid.uuid4(),
        "suite_id": uuid.uuid4(),
        "name": "Run #1",
        "system_prompt_snapshot": "Answer briefly.",
        "models": ["gpt-4o"],
        "scoring_method": "llm_judge",
        "temperature": 0.7,
        "reasoning_effort": None,
        "max_tokens": None,
        "judge_credential_id": JUDGE_CREDENTIAL_ID,
        "judge_model": "jev-latest",
        "status": "completed",
        "created_at": now,
        "completed_at": now,
        "results": [],
    }
    values.update(fields)
    return SimpleNamespace(**values)


class EvalRunApiTests(unittest.IsolatedAsyncioTestCase):
    """History, the history list and export all read the judge from these responses."""

    async def test_start_run_records_the_judge_and_hands_the_run_to_the_background(
        self,
    ) -> None:
        run = _stored_run(status="running", completed_at=None)
        body = RunEvalsRequest(
            credential_id=MAIN_CREDENTIAL_ID,
            models=["gpt-4o"],
            scoring_method="llm_judge",
            judge_credential_id=JUDGE_CREDENTIAL_ID,
            judge_model="jev-latest",
        )
        background = BackgroundTasks()
        with patch.object(eval_service, "create_run", AsyncMock(return_value=run)) as create:
            response = await evals_api.start_run(
                suite_id=run.suite_id,
                body=body,
                background_tasks=background,
                current_user=SimpleNamespace(id=uuid.uuid4()),
                db=AsyncMock(),
            )

        create_kwargs = create.await_args.kwargs
        self.assertEqual(create_kwargs["judge_credential_id"], JUDGE_CREDENTIAL_ID)
        self.assertEqual(create_kwargs["judge_model"], "jev-latest")
        self.assertEqual(response.judge_credential_id, JUDGE_CREDENTIAL_ID)
        self.assertEqual(response.judge_model, "jev-latest")
        self.assertEqual(len(background.tasks), 1)
        self.assertNotIn("judge_model", background.tasks[0].kwargs)

    async def test_start_run_turns_a_refused_judge_into_a_400(self) -> None:
        body = RunEvalsRequest(
            credential_id=MAIN_CREDENTIAL_ID,
            models=["gpt-4o"],
            scoring_method="llm_judge",
            judge_credential_id=JUDGE_CREDENTIAL_ID,
            judge_model="auto",
        )
        refusal = ValueError(
            "Judge credential must be an OpenAI, Google, OpenAI-compatible or "
            "Decision Model credential"
        )
        with (
            patch.object(eval_service, "create_run", AsyncMock(side_effect=refusal)),
            self.assertRaises(HTTPException) as ctx,
        ):
            await evals_api.start_run(
                suite_id=uuid.uuid4(),
                body=body,
                background_tasks=BackgroundTasks(),
                current_user=SimpleNamespace(id=uuid.uuid4()),
                db=AsyncMock(),
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Decision Model", str(ctx.exception.detail))

    async def test_get_run_returns_the_judge(self) -> None:
        run = _stored_run()
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=run))
        )

        response = await evals_api.get_run(
            run_id=run.id, current_user=SimpleNamespace(id=uuid.uuid4()), db=db
        )

        exported = response.model_dump(mode="json")
        self.assertEqual(exported["judge_credential_id"], str(JUDGE_CREDENTIAL_ID))
        self.assertEqual(exported["judge_model"], "jev-latest")

    async def test_the_history_list_names_the_judge(self) -> None:
        runs = [_stored_run(), _stored_run(scoring_method="exact_match", judge_model=None)]
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = runs
        db.execute = AsyncMock(return_value=result)

        listed = await evals_api.list_runs(
            suite_id=uuid.uuid4(), current_user=SimpleNamespace(id=uuid.uuid4()), db=db
        )

        self.assertEqual([item.judge_model for item in listed], ["jev-latest", None])


if __name__ == "__main__":
    unittest.main()
