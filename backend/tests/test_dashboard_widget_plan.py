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
from app.services.dashboard_data_context import TableContext, TableUnavailableError
from app.services.dashboard_widget_plan import (
    MAX_PROMPT_LENGTH,
    PLAN_SYSTEM_PROMPT,
    DetailPagePlan,
    WidgetExample,
    WidgetProposal,
    parse_widget_plan,
)


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


def _detail(**overrides: object) -> dict:
    detail = {
        "title": "Invoice details",
        "recordField": "invoice_id",
        "labelField": "vendor",
        "widgets": [
            {
                "title": "Invoice lines",
                "chartType": "table",
                "prompt": "Lines of the invoice whose invoice_id is $page.record.",
            },
            {"title": "Amount", "chartType": "numeric", "prompt": "The invoice's total."},
        ],
    }
    return {**detail, **overrides}


def _linked_table(**detail: object) -> dict:
    return {
        "title": "Recent invoices",
        "chartType": "bar",
        "prompt": "The latest invoices.",
        "example": {"labels": ["a"], "values": [1]},
        "detail": _detail(**detail),
    }


class DetailPagePlanTests(unittest.TestCase):
    def test_the_prompt_asks_for_one_table_that_opens_a_detail_page(self) -> None:
        self.assertIn("Always propose exactly one table", PLAN_SYSTEM_PROMPT)
        self.assertIn("$page.record", PLAN_SYSTEM_PROMPT)

    def test_a_table_carries_its_detail_page_and_names_the_record_column(self) -> None:
        proposals = parse_widget_plan(
            _answer([{"title": "Spend", "chartType": "bar", "prompt": "p"}, _linked_table()])
        )

        table = proposals[1]
        self.assertEqual((table.chart_type, table.example), ("table", None))
        self.assertTrue(table.prompt.startswith("The latest invoices. Show the invoice_id"))
        self.assertIn("the vendor column", table.prompt)
        self.assertEqual(
            table.detail,
            DetailPagePlan(
                title="Invoice details",
                record_field="invoice_id",
                label_field="vendor",
                widgets=[
                    WidgetProposal(
                        "Invoice lines",
                        "table",
                        "Lines of the invoice whose invoice_id is $page.record.",
                    ),
                    WidgetProposal(
                        "Amount",
                        "numeric",
                        "The invoice's total. On this detail page, read the record's invoice_id "
                        "from $page.record and show only that record's data.",
                    ),
                ],
            ),
        )
        self.assertIsNone(proposals[0].detail)

    def test_only_the_first_detail_page_is_kept(self) -> None:
        second = {**_linked_table(), "title": "Vendors"}

        proposals = parse_widget_plan(_answer([_linked_table(), second]))

        self.assertIsNotNone(proposals[0].detail)
        self.assertEqual((proposals[1].detail, proposals[1].chart_type), (None, "bar"))

    def test_a_detail_page_needs_a_record_column_and_a_widget(self) -> None:
        for detail in ({"recordField": ""}, {"widgets": []}, {"widgets": [{"title": "x"}]}):
            proposals = parse_widget_plan(_answer([_linked_table(**detail)]))

            self.assertIsNone(proposals[0].detail, detail)
            self.assertEqual(proposals[0].prompt, "The latest invoices.")

    def test_a_detail_page_without_a_title_or_label_is_named_after_its_table(self) -> None:
        proposals = parse_widget_plan(_answer([_linked_table(title="", labelField=None)]))

        detail = proposals[0].detail
        self.assertEqual((detail.title, detail.label_field), ("Recent invoices details", None))
        self.assertNotIn("column and the", proposals[0].prompt)

    def test_the_detail_table_stays_among_six_and_has_at_most_four_widgets(self) -> None:
        widgets = [{"title": f"W{i}", "chartType": "bar", "prompt": "p"} for i in range(7)]
        many = [{"title": f"D{i}", "chartType": "bar", "prompt": "p"} for i in range(6)]

        proposals = parse_widget_plan(_answer([*widgets, _linked_table(widgets=many)]))

        self.assertEqual([p.title for p in proposals][-2:], ["W4", "Recent invoices"])
        self.assertEqual(len(proposals), 6)
        self.assertEqual(len(proposals[-1].detail.widgets), 4)

    def test_long_prompts_still_fit_what_ai_generate_takes(self) -> None:
        long_table = {**_linked_table(), "prompt": "t" * 3000}
        long_detail = _detail(widgets=[{"title": "x", "chartType": "bar", "prompt": "d" * 3000}])

        table = parse_widget_plan(_answer([{**long_table, "detail": long_detail}]))[0]

        self.assertLessEqual(len(table.prompt), MAX_PROMPT_LENGTH)
        self.assertIn("invoice_id", table.prompt)
        self.assertLessEqual(len(table.detail.widgets[0].prompt), MAX_PROMPT_LENGTH)
        self.assertIn("$page.record", table.detail.widgets[0].prompt)


class WidgetExampleTests(unittest.TestCase):
    def test_a_proposal_keeps_a_preview_with_one_number_per_label(self) -> None:
        text = _answer(
            [
                {
                    "title": "Spend by source",
                    "chartType": "pie",
                    "prompt": "Sum amount by vendor_source.",
                    "example": {"labels": ["Google", "Meta"], "values": [160, 80.5]},
                }
            ]
        )

        self.assertEqual(
            parse_widget_plan(text)[0].example, WidgetExample(["Google", "Meta"], [160.0, 80.5])
        )

    def test_a_preview_that_does_not_add_up_is_dropped(self) -> None:
        for example in [
            {"labels": ["a", "b"], "values": [1]},
            {"labels": ["a"], "values": ["many"]},
            {"labels": ["a"], "values": [True]},
            {"labels": [], "values": []},
            {"labels": [str(i) for i in range(9)], "values": list(range(9))},
            "a chart",
        ]:
            text = _answer([{"title": "T", "chartType": "bar", "prompt": "p", "example": example}])
            self.assertIsNone(parse_widget_plan(text)[0].example, example)


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
                    {
                        "title": "Open cases",
                        "chart_type": "numeric",
                        "prompt": "Count them.",
                        "example": None,
                        "detail": None,
                    }
                ]
            },
        )
        self.assertEqual(planner.await_args.kwargs["session_id"], session_id)

    async def test_returns_the_detail_page_of_the_linked_table(self) -> None:
        detail = DetailPagePlan(
            "Case details", "case_id", None, [WidgetProposal("Timeline", "line", "p")]
        )
        planner = AsyncMock(return_value=[WidgetProposal("Cases", "table", "t", None, detail)])

        with (
            patch.object(
                dash_api, "get_credential_for_user", AsyncMock(return_value=_credential())
            ),
            patch.object(dash_api, "plan_dashboard_widgets", planner),
        ):
            response = await dash_api.ai_plan_widgets(
                body=self._body(), current_user=_user(), db=MagicMock()
            )

        self.assertEqual(
            response.widgets[0].detail.model_dump(),
            {
                "title": "Case details",
                "record_field": "case_id",
                "label_field": None,
                "widgets": [
                    {
                        "title": "Timeline",
                        "chart_type": "line",
                        "prompt": "p",
                        "example": None,
                        "detail": None,
                    }
                ],
            },
        )

    async def test_a_page_about_a_table_is_planned_from_its_data(self) -> None:
        table_id = uuid.uuid4()
        table = TableContext(table_id, "Invoices", 2, [], [])
        loader = AsyncMock(return_value=[table])
        proposal = WidgetProposal("By source", "pie", "p", WidgetExample(["Google"], [3.0]))
        planner = AsyncMock(return_value=[proposal])
        body = self._body()
        body.data_table_ids = [table_id]

        with (
            patch.object(
                dash_api, "get_credential_for_user", AsyncMock(return_value=_credential())
            ),
            patch.object(dash_api, "load_table_contexts", loader),
            patch.object(dash_api, "plan_dashboard_widgets", planner),
        ):
            response = await dash_api.ai_plan_widgets(
                body=body, current_user=_user(), db=MagicMock()
            )

        self.assertEqual(loader.await_args.args[1], [table_id])
        self.assertIn('"Invoices"', planner.await_args.kwargs["data_context"])
        self.assertEqual(
            response.widgets[0].example.model_dump(), {"labels": ["Google"], "values": [3.0]}
        )

    async def test_a_table_the_user_cannot_read_is_a_404(self) -> None:
        body = self._body()
        body.data_table_ids = [uuid.uuid4()]
        loader = AsyncMock(side_effect=TableUnavailableError(body.data_table_ids[0]))

        with (
            patch.object(
                dash_api, "get_credential_for_user", AsyncMock(return_value=_credential())
            ),
            patch.object(dash_api, "load_table_contexts", loader),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await dash_api.ai_plan_widgets(body=body, current_user=_user(), db=MagicMock())

        self.assertEqual(ctx.exception.status_code, 404)

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


def _dashboard_db(dashboard: MagicMock) -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=dashboard))
    )
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


_DSL = {"nodes": [{"id": "c", "type": "chartOutput", "data": {"chartType": "bar"}}], "edges": []}


class AiGenerateTableTests(unittest.IsolatedAsyncioTestCase):
    def _body(self) -> AiWidgetRequest:
        return AiWidgetRequest(
            prompt="Spend by vendor_source",
            credential_id=uuid.uuid4(),
            model="gpt-4o",
            data_table_ids=[uuid.UUID(int=7)],
        )

    async def test_the_builder_gets_the_tables_id_and_columns(self) -> None:
        user = _user()
        dashboard = MagicMock(id=uuid.uuid4(), owner_id=user.id, name="Spend")
        table = TableContext(uuid.UUID(int=7), "Invoices", 2, [], [])
        generate = AsyncMock(return_value=_DSL)

        with (
            patch.object(dash_api, "generate_widget_dsl", generate),
            patch.object(
                dash_api, "get_credential_for_user", AsyncMock(return_value=_credential())
            ),
            patch.object(dash_api, "load_table_contexts", AsyncMock(return_value=[table])),
            patch.object(dash_api, "_widget_to_response", MagicMock()),
        ):
            await dash_api.ai_generate_widget(
                dashboard_id=dashboard.id,
                body=self._body(),
                current_user=user,
                db=_dashboard_db(dashboard),
            )

        prompt = generate.await_args.args[0]
        self.assertTrue(prompt.startswith("Spend by vendor_source"))
        self.assertIn(f"dataTableId: {uuid.UUID(int=7)}", prompt)

    async def test_a_table_the_pages_owner_cannot_read_is_refused(self) -> None:
        user = _user()
        dashboard = MagicMock(id=uuid.uuid4(), owner_id=uuid.uuid4(), name="Spend")
        table = TableContext(uuid.UUID(int=7), "Invoices", 2, [], [])
        loader = AsyncMock(side_effect=[[table], TableUnavailableError(table.id)])
        generate = AsyncMock(return_value=_DSL)

        with (
            patch.object(dash_api, "generate_widget_dsl", generate),
            patch.object(
                dash_api, "get_credential_for_user", AsyncMock(return_value=_credential())
            ),
            patch.object(dash_api, "load_table_contexts", loader),
            patch.object(
                dash_api,
                "dashboard_permission",
                AsyncMock(return_value=dash_api.PERMISSION_WRITE),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await dash_api.ai_generate_widget(
                    dashboard_id=dashboard.id,
                    body=self._body(),
                    current_user=user,
                    db=_dashboard_db(dashboard),
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(loader.await_args.args[2], dashboard.owner_id)
        generate.assert_not_awaited()


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

    async def test_an_answer_without_json_is_asked_again_for_json_only(self) -> None:
        execute_llm = AsyncMock(
            side_effect=[
                {"text": "First I will look at the table, then build the chart."},
                {
                    "text": '{"nodes": [{"id": "c", "type": "chartOutput", "data": {}}], "edges": []}'
                },
            ]
        )

        with (
            patch.object(dash_api, "decrypt_config", return_value={"api_key": "x"}),
            patch.object(dash_api, "execute_llm", execute_llm),
        ):
            dsl = await dash_api.generate_widget_dsl(
                "show", credential=_credential(), model="m", user=_user()
            )

        self.assertEqual(dsl["nodes"][0]["type"], "chartOutput")
        retry = execute_llm.await_args_list[1].kwargs["user_message"]
        self.assertIn("workflow JSON object only", retry)
        self.assertIn("JSON object only", dash_api._AI_WIDGET_SUFFIX)

    async def test_two_answers_without_json_are_a_422(self) -> None:
        execute_llm = AsyncMock(return_value={"text": "I cannot build that."})

        with (
            patch.object(dash_api, "decrypt_config", return_value={"api_key": "x"}),
            patch.object(dash_api, "execute_llm", execute_llm),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await dash_api.generate_widget_dsl(
                    "show", credential=_credential(), model="m", user=_user()
                )

        self.assertEqual((ctx.exception.status_code, execute_llm.await_count), (422, 2))

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
