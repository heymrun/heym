import json
import unittest
import uuid

from app.services.alerts.ai_draft import build_draft_system_prompt, parse_draft_response


class TestParseDraftResponse(unittest.TestCase):
    def test_valid_json_becomes_a_draft(self):
        workflow_id = uuid.uuid4()
        raw = json.dumps(
            {
                "name": "Invoice sync failures",
                "alert_type": "error_threshold",
                "scope": "workflow",
                "workflow_id": str(workflow_id),
                "config": {"window_minutes": 10, "threshold_count": 5},
                "renotify_mode": "on_recovery",
                "filled_fields": ["name", "alert_type", "config"],
            }
        )
        draft, clarification = parse_draft_response(raw)
        self.assertIsNotNone(draft)
        self.assertIsNone(clarification)
        self.assertEqual(draft.config["threshold_count"], 5)
        self.assertEqual(draft.workflow_id, workflow_id)

    def test_fenced_json_is_unwrapped(self):
        raw = (
            "```json\n"
            '{"name":"X","alert_type":"execution_count","scope":"system",'
            '"config":{"window_minutes":60,"threshold_count":100}}\n'
            "```"
        )
        draft, clarification = parse_draft_response(raw)
        self.assertIsNotNone(draft)
        self.assertEqual(draft.alert_type, "execution_count")

    def test_prose_returns_clarification_not_a_draft(self):
        draft, clarification = parse_draft_response(
            "Which workflow did you mean? You have three with 'invoice' in the name."
        )
        self.assertIsNone(draft)
        self.assertIn("Which workflow", clarification)

    def test_empty_response_returns_clarification(self):
        draft, clarification = parse_draft_response("")
        self.assertIsNone(draft)
        self.assertIsNotNone(clarification)

    def test_malformed_json_returns_clarification(self):
        draft, clarification = parse_draft_response('{"name": "X", broken')
        self.assertIsNone(draft)
        self.assertIsNotNone(clarification)

    def test_a_partial_config_is_completed_from_the_type_defaults(self):
        # The model named only the window. That is still a usable condition:
        # its value wins and the rest of the fields come from the defaults.
        raw = json.dumps(
            {
                "name": "X",
                "alert_type": "token_cost",
                "scope": "system",
                "config": {"window_minutes": 60},
            }
        )
        draft, clarification = parse_draft_response(raw)
        self.assertIsNotNone(draft)
        self.assertEqual(draft.config["window_minutes"], 60)
        self.assertEqual(draft.config["metric"], "usd")
        self.assertEqual(draft.config["threshold"], 25)
        self.assertIsNone(clarification)

    def test_a_config_that_cannot_be_repaired_falls_back_to_the_defaults(self):
        raw = json.dumps(
            {
                "name": "X",
                "alert_type": "error_threshold",
                "scope": "system",
                "config": {"window_minutes": -5, "threshold_count": 0},
            }
        )
        draft, _ = parse_draft_response(raw)
        self.assertIsNotNone(draft)
        self.assertEqual(draft.config, {"window_minutes": 15, "threshold_count": 5})

    def test_workflow_scope_without_a_workflow_id_still_drafts(self):
        # This is the vague-request case: everything but the workflow is known,
        # so the wizard should open on Scope rather than discard the condition.
        raw = json.dumps(
            {
                "name": "X",
                "alert_type": "error_threshold",
                "scope": "workflow",
                "config": {"window_minutes": 10, "threshold_count": 5},
            }
        )
        draft, clarification = parse_draft_response(raw)
        self.assertIsNotNone(draft)
        self.assertEqual(draft.scope, "workflow")
        self.assertIsNone(draft.workflow_id)
        self.assertEqual(draft.config["threshold_count"], 5)
        self.assertIn("which workflow", clarification)

    def test_a_type_only_answer_still_drafts(self):
        draft, clarification = parse_draft_response('{"alert_type": "execution_count"}')
        self.assertIsNotNone(draft)
        self.assertEqual(draft.alert_type, "execution_count")
        self.assertEqual(draft.config, {"window_minutes": 60, "threshold_count": 100})
        self.assertIsNone(draft.name)
        self.assertIn("a name", clarification)

    def test_an_unknown_alert_type_keeps_the_rest(self):
        raw = json.dumps({"name": "X", "alert_type": "made_up", "scope": "system"})
        draft, clarification = parse_draft_response(raw)
        self.assertIsNotNone(draft)
        self.assertIsNone(draft.alert_type)
        self.assertIsNone(draft.config)
        self.assertEqual(draft.name, "X")
        self.assertIn("threshold", clarification)

    def test_a_json_object_with_nothing_usable_returns_no_draft(self):
        draft, clarification = parse_draft_response('{"unrelated": true}')
        self.assertIsNone(draft)
        self.assertIsNotNone(clarification)

    def test_a_non_uuid_workflow_id_is_dropped_not_fatal(self):
        raw = json.dumps(
            {
                "name": "X",
                "alert_type": "error_threshold",
                "scope": "workflow",
                "workflow_id": "the invoice one",
                "config": {"window_minutes": 10, "threshold_count": 5},
            }
        )
        draft, clarification = parse_draft_response(raw)
        self.assertIsNotNone(draft)
        self.assertIsNone(draft.workflow_id)
        self.assertIn("which workflow", clarification)

    def test_system_scope_drops_a_stray_workflow_id(self):
        raw = json.dumps(
            {
                "name": "X",
                "alert_type": "execution_count",
                "scope": "system",
                "workflow_id": str(uuid.uuid4()),
                "config": {"window_minutes": 60, "threshold_count": 10},
            }
        )
        draft, clarification = parse_draft_response(raw)
        self.assertIsNotNone(draft)
        self.assertIsNone(draft.workflow_id)

    def test_asking_to_be_notified_requests_a_new_workflow(self):
        raw = json.dumps(
            {
                "name": "X",
                "alert_type": "error_threshold",
                "scope": "system",
                "config": {"window_minutes": 10, "threshold_count": 5},
                "create_notify_workflow": True,
            }
        )
        draft, _ = parse_draft_response(raw)
        self.assertIs(draft.create_notify_workflow, True)

    def test_wanting_nothing_to_run_is_carried_through(self):
        raw = json.dumps(
            {
                "name": "X",
                "alert_type": "error_threshold",
                "scope": "system",
                "config": {"window_minutes": 10, "threshold_count": 5},
                "create_notify_workflow": False,
            }
        )
        draft, _ = parse_draft_response(raw)
        self.assertIs(draft.create_notify_workflow, False)

    def test_an_existing_workflow_beats_the_create_flag(self):
        # Honouring both would leave an empty workflow nobody asked for.
        raw = json.dumps(
            {
                "name": "X",
                "alert_type": "error_threshold",
                "scope": "system",
                "config": {"window_minutes": 10, "threshold_count": 5},
                "notify_workflow_id": str(uuid.uuid4()),
                "create_notify_workflow": True,
            }
        )
        draft, _ = parse_draft_response(raw)
        self.assertIs(draft.create_notify_workflow, False)
        self.assertIsNotNone(draft.notify_workflow_id)

    def test_silence_leaves_the_notify_choice_to_the_wizard(self):
        raw = json.dumps(
            {
                "name": "X",
                "alert_type": "error_threshold",
                "scope": "system",
                "config": {"window_minutes": 10, "threshold_count": 5},
            }
        )
        draft, _ = parse_draft_response(raw)
        self.assertIsNone(draft.create_notify_workflow)

    def test_cooldown_without_minutes_still_drafts(self):
        raw = json.dumps(
            {
                "name": "X",
                "alert_type": "execution_count",
                "scope": "system",
                "config": {"window_minutes": 60, "threshold_count": 10},
                "renotify_mode": "cooldown",
            }
        )
        draft, clarification = parse_draft_response(raw)
        self.assertIsNotNone(draft)
        self.assertEqual(draft.renotify_mode, "cooldown")
        self.assertIsNone(draft.cooldown_minutes)
        self.assertIn("how often", clarification)


class TestDraftSystemPrompt(unittest.TestCase):
    def test_prompt_lists_the_available_workflows(self):
        wf_id = uuid.uuid4()
        prompt = build_draft_system_prompt([(wf_id, "Invoice Sync")])
        self.assertIn("Invoice Sync", prompt)
        self.assertIn(str(wf_id), prompt)

    def test_prompt_names_all_four_alert_types(self):
        prompt = build_draft_system_prompt([])
        for alert_type in (
            "error_threshold",
            "workflow_duration",
            "token_cost",
            "execution_count",
        ):
            self.assertIn(alert_type, prompt)

    def test_prompt_forbids_inventing_a_workflow_id(self):
        self.assertIn("Never invent a workflow_id", build_draft_system_prompt([]))

    def test_prompt_asks_for_partial_answers(self):
        prompt = build_draft_system_prompt([])
        self.assertIn("A partial answer", prompt)

    def test_prompt_requires_a_description(self):
        prompt = build_draft_system_prompt([])
        self.assertIn("description   REQUIRED", prompt)
