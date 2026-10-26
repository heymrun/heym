"""Prompt suites through the service the Evals routes and the chat tools share.

Requires a reachable PostgreSQL instance with migrations applied.
"""

import unittest
import uuid
from types import SimpleNamespace

from sqlalchemy import delete

from app.db.models import AgentSuite, Credential, CredentialType, User, Workflow
from app.db.session import async_session_maker, engine
from app.models.eval_schemas import (
    EvalSuiteCreate,
    EvalSuiteUpdate,
    EvalTestCaseCreate,
    EvalTestCaseUpdate,
    EvalTestCaseUpsert,
    RunEvalsRequest,
)
from app.services import eval_service
from app.services import prompt_suite_service as prompt_suites
from app.services.eval_common import EvalNotFoundError


class ScoreTests(unittest.TestCase):
    def test_scores_map_to_percent(self) -> None:
        scores = ("pass", "partial", "fail", "73", "250", "x")
        self.assertEqual(
            [prompt_suites.score_to_pct(score) for score in scores], [100, 50, 0, 73, 100, 0]
        )
        self.assertTrue(prompt_suites.is_passing("50"))
        self.assertFalse(prompt_suites.is_passing("49"))

    def test_only_known_scoring_methods_pass(self) -> None:
        prompt_suites.check_scoring_method("llm_judge")
        prompt_suites.check_scoring_method(None)
        with self.assertRaises(ValueError):
            prompt_suites.check_scoring_method("regex")


class RealPostgresPromptSuiteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.owner_id = uuid.uuid4()
        self.outsider_id = uuid.uuid4()
        self.credential_id = uuid.uuid4()
        self.outsider_credential_id = uuid.uuid4()
        async with async_session_maker() as session:
            session.add_all(
                [
                    User(
                        id=user_id,
                        email=f"prompt_suite_{user_id.hex[:8]}@example.com",
                        hashed_password="x",
                        name="User",
                    )
                    for user_id in (self.owner_id, self.outsider_id)
                ]
            )
            await session.flush()
            session.add_all(
                [
                    Credential(
                        id=self.credential_id,
                        owner_id=self.owner_id,
                        name=f"openai-{self.credential_id.hex[:6]}",
                        type=CredentialType.openai,
                        encrypted_config="x",
                    ),
                    Credential(
                        id=self.outsider_credential_id,
                        owner_id=self.outsider_id,
                        name=f"theirs-{self.outsider_credential_id.hex[:6]}",
                        type=CredentialType.openai,
                        encrypted_config="x",
                    ),
                ]
            )
            await session.commit()

    async def asyncTearDown(self) -> None:
        user_ids = [self.owner_id, self.outsider_id]
        async with async_session_maker() as session:
            await session.execute(delete(Workflow).where(Workflow.owner_id.in_(user_ids)))
            await session.execute(delete(Credential).where(Credential.owner_id.in_(user_ids)))
            await session.execute(delete(User).where(User.id.in_(user_ids)))
            await session.commit()
        await engine.dispose()

    async def test_create_and_update_check_the_scoring_method(self) -> None:
        async with async_session_maker() as db:
            suite = await prompt_suites.create_prompt_suite(
                db,
                self.owner_id,
                EvalSuiteCreate(name="Support", system_prompt="Answer.", scoring_method="contains"),
            )
            self.assertEqual(suite.test_cases, [])
            updated = await prompt_suites.update_prompt_suite(
                db, suite, EvalSuiteUpdate(name="Support v2")
            )
            self.assertEqual((updated.name, updated.scoring_method), ("Support v2", "contains"))
            with self.assertRaises(ValueError):
                await prompt_suites.create_prompt_suite(
                    db, self.owner_id, EvalSuiteCreate(name="Bad", scoring_method="regex")
                )

    async def test_test_case_changes_apply_together(self) -> None:
        async with async_session_maker() as db:
            suite = await prompt_suites.create_prompt_suite(
                db, self.owner_id, EvalSuiteCreate(name="Math")
            )
            first = await prompt_suites.add_test_case(
                db, suite.id, EvalTestCaseCreate(input="1+1", expected_output="2")
            )
            second = await prompt_suites.add_test_case(
                db, suite.id, EvalTestCaseCreate(input="2+2", expected_output="4")
            )
            suite = await prompt_suites.load_owned_prompt_suite(
                db, suite.id, self.owner_id, with_test_cases=True
            )
            suite = await prompt_suites.apply_test_case_changes(
                db,
                suite,
                [
                    EvalTestCaseUpsert(id=first.id, expected_output="two"),
                    EvalTestCaseUpsert(input="3+3", expected_output="6"),
                ],
                [second.id],
            )
        self.assertEqual(
            [(tc.input, tc.expected_output, tc.order_index) for tc in suite.test_cases],
            [("1+1", "two", 0), ("3+3", "6", 2)],
        )

    async def test_an_unknown_test_case_id_writes_nothing(self) -> None:
        async with async_session_maker() as db:
            suite = await prompt_suites.create_prompt_suite(
                db, self.owner_id, EvalSuiteCreate(name="Math")
            )
            await prompt_suites.add_test_case(
                db, suite.id, EvalTestCaseCreate(input="1+1", expected_output="2")
            )
            suite = await prompt_suites.load_owned_prompt_suite(
                db, suite.id, self.owner_id, with_test_cases=True
            )
            with self.assertRaises(ValueError):
                await prompt_suites.apply_test_case_changes(
                    db, suite, [EvalTestCaseUpsert(input="new")], [uuid.uuid4()]
                )
        async with async_session_maker() as db:
            reloaded = await prompt_suites.load_owned_prompt_suite(
                db, suite.id, self.owner_id, with_test_cases=True
            )
        self.assertEqual([tc.input for tc in reloaded.test_cases], ["1+1"])

    async def test_another_user_cannot_reach_the_suite_or_its_cases(self) -> None:
        async with async_session_maker() as db:
            suite = await prompt_suites.create_prompt_suite(
                db, self.owner_id, EvalSuiteCreate(name="Private")
            )
            case = await prompt_suites.add_test_case(db, suite.id, EvalTestCaseCreate(input="a"))
            for call in (
                prompt_suites.load_owned_prompt_suite(db, suite.id, self.outsider_id),
                prompt_suites.update_test_case(
                    db, suite.id, case.id, self.outsider_id, EvalTestCaseUpdate(input="b")
                ),
                prompt_suites.delete_test_case(db, suite.id, case.id, self.outsider_id),
                prompt_suites.owned_suite_type(db, suite.id, self.outsider_id),
            ):
                with self.assertRaises(EvalNotFoundError):
                    await call

    async def test_suite_types_and_the_combined_list(self) -> None:
        workflow_id = uuid.uuid4()
        async with async_session_maker() as db:
            prompt = await prompt_suites.create_prompt_suite(
                db, self.owner_id, EvalSuiteCreate(name="Prompt")
            )
            db.add(
                Workflow(id=workflow_id, name="Flow", owner_id=self.owner_id, nodes=[], edges=[])
            )
            await db.flush()
            agent = AgentSuite(
                owner_id=self.owner_id,
                name="Agent",
                workflow_id=workflow_id,
                node_id="agent-1",
                node_label="Agent",
                tool_assertions=[],
                thresholds={},
                baseline={},
            )
            db.add(agent)
            await db.commit()
            self.assertEqual(
                await prompt_suites.owned_suite_type(db, prompt.id, self.owner_id), "prompt"
            )
            self.assertEqual(
                await prompt_suites.owned_suite_type(db, agent.id, self.owner_id), "agent"
            )
            listed = await prompt_suites.list_all_suites(db, self.owner_id)
        self.assertEqual(
            {(item.name, item.suite_type) for item in listed},
            {("Prompt", "prompt"), ("Agent", "agent")},
        )

    async def test_launch_creates_a_running_row_and_its_job(self) -> None:
        owner = SimpleNamespace(id=self.owner_id)
        async with async_session_maker() as db:
            suite = await prompt_suites.create_prompt_suite(
                db, self.owner_id, EvalSuiteCreate(name="Math")
            )
            launch = await prompt_suites.launch_prompt_run(
                db,
                owner,
                suite.id,
                RunEvalsRequest(credential_id=self.credential_id, models=["gpt-4o"]),
            )
        self.assertEqual(launch.run.status, "running")
        self.assertIs(launch.job.func, eval_service.execute_evals_for_run)
        self.assertEqual(launch.job.kwargs["run_id"], launch.run.id)
        self.assertEqual(launch.job.kwargs["models"], ["gpt-4o"])
        async with async_session_maker() as db:
            run = await prompt_suites.load_owned_prompt_run(db, launch.run.id, self.owner_id)
            with self.assertRaises(EvalNotFoundError):
                await prompt_suites.load_owned_prompt_run(db, launch.run.id, self.outsider_id)
            listed = await prompt_suites.list_prompt_runs(db, suite.id, self.owner_id)
        self.assertEqual(prompt_suites.prompt_run_response(run, run.results).status, "running")
        self.assertEqual([item.id for item in listed], [launch.run.id])

    async def test_launch_refuses_another_users_credential(self) -> None:
        async with async_session_maker() as db:
            suite = await prompt_suites.create_prompt_suite(
                db, self.owner_id, EvalSuiteCreate(name="Math")
            )
            with self.assertRaises(ValueError):
                await prompt_suites.launch_prompt_run(
                    db,
                    SimpleNamespace(id=self.owner_id),
                    suite.id,
                    RunEvalsRequest(credential_id=self.outsider_credential_id, models=["gpt-4o"]),
                )


if __name__ == "__main__":
    unittest.main()
