"""Planning a dashboard page's widgets from a description, and building them in one session."""

import json
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import dashboards as dash_api
from app.db.models import CredentialType
from app.models.dashboard_schemas import AiPlanRequest, AiWidgetRequest
from app.services import dashboard_widget_plan as plan
from app.services.dashboard_widget_plan import WidgetProposal, parse_widget_plan


def _user() -> MagicMock:
    return MagicMock(id=uuid.uuid4())


def _credential(kind: CredentialType = CredentialType.openai) -> MagicMock:
    credential = MagicMock(id=uuid.uuid4(), type=kind, encrypted_config="enc")
    credential.name = "Model"
    return credential


def _answer(widgets: list[dict]) -> str:
    return "```json\n" + json.dumps({"widgets": widgets}) + "\n```"


class ParseWidgetPlanTests(unittest.TestCase):
    def test_reads_a_fenced_answer_and_maps_chart_types(self) -> None:
        text = _answer(
            [
                {"title": "Open cases", "chartType": "numeric", "prompt": "Count open cases."},
                {
                    "title": "Cases by priority",
                    "chartType": "donut",
                    "prompt": "Group by priority.",
                },
            ]
        )

        self.assertEqual(
            parse_widget_plan(text),
            [
                WidgetProposal("Open cases", "numeric", "Count open cases."),
                WidgetProposal("Cases by priority", "bar", "Group by priority."),
            ],
        )

    def test_reads_bare_json_inside_prose(self) -> None:
        text = 'Here you go: {"widgets": [{"title": "Notes", "chartType": "text", "prompt": "A note."}]}'

        self.assertEqual(parse_widget_plan(text), [WidgetProposal("Notes", "text", "A note.")])

    def test_drops_items_without_a_title_or_prompt_and_keeps_six(self) -> None:
        widgets = [{"title": f"W{i}", "chartType": "bar", "prompt": "p"} for i in range(9)]
        widgets.insert(0, {"title": "", "prompt": "no title"})
        widgets.insert(1, {"title": "No prompt"})
        widgets.insert(2, "not an object")

        proposals = parse_widget_plan(_answer(widgets))

        self.assertEqual([p.title for p in proposals], ["W0", "W1", "W2", "W3", "W4", "W5"])

    def test_an_answer_that_is_not_a_plan_gives_nothing(self) -> None:
        for text in ["", "no json here", "{not json}", '{"widgets": "many"}', "[1, 2]"]:
            self.assertEqual(parse_widget_plan(text), [], text)

    def test_long_titles_and_prompts_are_cut_to_what_ai_generate_takes(self) -> None:
        proposals = parse_widget_plan(_answer([{"title": "t" * 200, "prompt": "p" * 3000}]))

        self.assertEqual((len(proposals[0].title), len(proposals[0].prompt)), (80, 2000))


class PlanDashboardWidgetsTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_plan_runs_in_the_given_session_with_its_own_trace_source(self) -> None:
        user, credential, session_id = _user(), _credential(), uuid.uuid4()
        execute_llm = AsyncMock(
            return_value={"text": _answer([{"title": "A", "chartType": "bar", "prompt": "B"}])}
        )

        with (
            patch.object(plan, "decrypt_config", return_value={"api_key": "x"}),
            patch.object(plan, "execute_llm", execute_llm),
        ):
            proposals = await plan.plan_dashboard_widgets(
                "Support overview",
                credential=credential,
                model="gpt-4o",
                user=user,
                session_id=session_id,
            )

        self.assertEqual(proposals, [WidgetProposal("A", "bar", "B")])
        kwargs = execute_llm.await_args.kwargs
        self.assertIn("Support overview", kwargs["user_message"])
        self.assertEqual(kwargs["system_instruction"], plan.PLAN_SYSTEM_PROMPT)
        trace = kwargs["trace_context"]
        self.assertEqual((trace.user_id, trace.credential_id), (user.id, credential.id))
        self.assertEqual(trace.source, "dashboard_widget_plan")
        self.assertEqual(trace.session_id, str(session_id))

    async def test_without_a_session_the_llm_service_picks_one(self) -> None:
        execute_llm = AsyncMock(return_value={"text": ""})

        with (
            patch.object(plan, "decrypt_config", return_value={"api_key": "x"}),
            patch.object(plan, "execute_llm", execute_llm),
        ):
            await plan.plan_dashboard_widgets(
                "x", credential=_credential(), model="m", user=_user()
            )

        self.assertIsNone(execute_llm.await_args.kwargs["trace_context"].session_id)


class AiPlanEndpointTests(unittest.IsolatedAsyncioTestCase):
    def _body(self, session_id: uuid.UUID | None = None) -> AiPlanRequest:
        return AiPlanRequest(
            description="Support overview",
            credential_id=uuid.uuid4(),
            model="gpt-4o",
            session_id=session_id,
        )

    async def test_returns_the_proposals(self) -> None:
        session_id = uuid.uuid4()
        planner = AsyncMock(return_value=[WidgetProposal("Open cases", "numeric", "Count them.")])

        with (
            patch.object(
                dash_api, "get_credential_for_user", AsyncMock(return_value=_credential())
            ),
            patch.object(dash_api, "plan_dashboard_widgets", planner),
        ):
            response = await dash_api.ai_plan_widgets(
                body=self._body(session_id), current_user=_user(), db=MagicMock()
            )

        self.assertEqual(
            response.model_dump(),
            {
                "widgets": [
                    {"title": "Open cases", "chart_type": "numeric", "prompt": "Count them."}
                ]
            },
        )
        self.assertEqual(planner.await_args.kwargs["session_id"], session_id)

    async def test_refuses_a_missing_or_non_llm_credential(self) -> None:
        for credential, code in [(None, 404), (_credential(CredentialType.slack), 400)]:
            with patch.object(
                dash_api, "get_credential_for_user", AsyncMock(return_value=credential)
            ):
                with self.assertRaises(HTTPException) as ctx:
                    await dash_api.ai_plan_widgets(
                        body=self._body(), current_user=_user(), db=MagicMock()
                    )
            self.assertEqual(ctx.exception.status_code, code)

    async def test_no_proposals_is_a_422(self) -> None:
        with (
            patch.object(
                dash_api, "get_credential_for_user", AsyncMock(return_value=_credential())
            ),
            patch.object(dash_api, "plan_dashboard_widgets", AsyncMock(return_value=[])),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await dash_api.ai_plan_widgets(
                    body=self._body(), current_user=_user(), db=MagicMock()
                )

        self.assertEqual(ctx.exception.status_code, 422)


class AiGenerateSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_widget_is_built_in_the_plan_session(self) -> None:
        user = _user()
        dashboard = MagicMock(id=uuid.uuid4(), owner_id=user.id, name="Support")
        db = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=dashboard))
        )
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        session_id = uuid.uuid4()
        dsl = {
            "nodes": [{"id": "c", "type": "chartOutput", "data": {"chartType": "bar"}}],
            "edges": [],
        }
        generate = AsyncMock(return_value=dsl)

        with (
            patch.object(dash_api, "generate_widget_dsl", generate),
            patch.object(
                dash_api, "get_credential_for_user", AsyncMock(return_value=_credential())
            ),
            patch.object(dash_api, "_widget_to_response", MagicMock()),
        ):
            await dash_api.ai_generate_widget(
                dashboard_id=dashboard.id,
                body=AiWidgetRequest(
                    prompt="Open cases",
                    credential_id=uuid.uuid4(),
                    model="gpt-4o",
                    session_id=session_id,
                ),
                current_user=user,
                db=db,
            )

        self.assertEqual(generate.await_args.kwargs["session_id"], session_id)

    async def test_generate_widget_dsl_puts_the_session_on_the_trace(self) -> None:
        session_id = uuid.uuid4()
        execute_llm = AsyncMock(
            return_value={
                "text": '{"nodes": [{"id": "c", "type": "chartOutput", "data": {}}], "edges": []}'
            }
        )

        with (
            patch.object(dash_api, "decrypt_config", return_value={"api_key": "x"}),
            patch.object(dash_api, "execute_llm", execute_llm),
        ):
            await dash_api.generate_widget_dsl(
                "show", credential=_credential(), model="m", user=_user(), session_id=session_id
            )

        self.assertEqual(execute_llm.await_args.kwargs["trace_context"].session_id, str(session_id))
