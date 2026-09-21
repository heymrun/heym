"""AI-assisted decision question drafting."""

import unittest

from app.api.decisions import extract_questions_payload, normalize_generated_questions


class ExtractQuestionsPayloadTests(unittest.TestCase):
    def test_plain_json_object(self) -> None:
        self.assertEqual(extract_questions_payload('{"questions": []}'), {"questions": []})

    def test_fenced_json_block(self) -> None:
        payload = extract_questions_payload('```json\n{"questions": []}\n```')
        self.assertEqual(payload, {"questions": []})

    def test_prose_around_the_object(self) -> None:
        payload = extract_questions_payload('Sure!\n{"questions": [], "state": "x"}\nDone.')
        self.assertEqual(payload, {"questions": [], "state": "x"})

    def test_unparseable_text_returns_none(self) -> None:
        self.assertIsNone(extract_questions_payload("I could not do that."))

    def test_a_json_array_is_not_accepted(self) -> None:
        self.assertIsNone(extract_questions_payload("[1, 2, 3]"))


class NormalizeGeneratedQuestionsTests(unittest.TestCase):
    def test_noul_question(self) -> None:
        rows = normalize_generated_questions(
            [
                {
                    "id": "Is Urgent!",
                    "type": "noul",
                    "instructions": "Urgent?",
                    "criteria": {"true": "yes side", "false": "no side"},
                }
            ],
            set(),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "is_urgent")
        self.assertEqual(rows[0]["criteriaTrue"], "yes side")
        self.assertEqual(rows[0]["criteriaFalse"], "no side")

    def test_noul_without_criteria_still_survives(self) -> None:
        rows = normalize_generated_questions(
            [{"id": "q", "type": "noul", "instructions": "Urgent?"}], set()
        )
        self.assertEqual(len(rows), 1)
        self.assertNotIn("criteriaTrue", rows[0])

    def test_choice_question_becomes_options(self) -> None:
        rows = normalize_generated_questions(
            [
                {
                    "id": "department",
                    "type": "choice",
                    "instructions": "Which team?",
                    "criteria": {"billing": "Payments", "technical": "Bugs"},
                }
            ],
            set(),
        )
        self.assertEqual(
            rows[0]["options"],
            [
                {"key": "billing", "description": "Payments"},
                {"key": "technical", "description": "Bugs"},
            ],
        )

    def test_choice_without_criteria_is_dropped(self) -> None:
        rows = normalize_generated_questions(
            [{"id": "q", "type": "choice", "instructions": "Which?"}], set()
        )
        self.assertEqual(rows, [])

    def test_score_question_becomes_levels(self) -> None:
        rows = normalize_generated_questions(
            [
                {
                    "id": "frustration",
                    "type": "score",
                    "instructions": "How frustrated?",
                    "criteria": ["Calm", "Angry"],
                }
            ],
            set(),
        )
        self.assertEqual(rows[0]["levels"], ["Calm", "Angry"])

    def test_score_with_one_level_is_dropped(self) -> None:
        rows = normalize_generated_questions(
            [{"id": "q", "type": "score", "instructions": "How bad?", "criteria": ["Calm"]}],
            set(),
        )
        self.assertEqual(rows, [])

    def test_unknown_type_is_dropped(self) -> None:
        rows = normalize_generated_questions(
            [{"id": "q", "type": "nuol", "instructions": "?"}], set()
        )
        self.assertEqual(rows, [])

    def test_question_without_instructions_is_dropped(self) -> None:
        self.assertEqual(normalize_generated_questions([{"id": "q", "type": "noul"}], set()), [])

    def test_an_id_colliding_with_an_existing_one_is_suffixed(self) -> None:
        rows = normalize_generated_questions(
            [{"id": "urgent", "type": "noul", "instructions": "?"}], {"urgent"}
        )
        self.assertEqual(rows[0]["id"], "urgent_2")

    def test_duplicate_ids_within_one_batch_are_suffixed(self) -> None:
        rows = normalize_generated_questions(
            [
                {"id": "q", "type": "noul", "instructions": "A?"},
                {"id": "q", "type": "noul", "instructions": "B?"},
            ],
            set(),
        )
        self.assertEqual([row["id"] for row in rows], ["q", "q_2"])

    def test_a_dropped_question_does_not_consume_an_id(self) -> None:
        rows = normalize_generated_questions(
            [
                {"id": "q", "type": "choice", "instructions": "Dropped, no criteria"},
                {"id": "q", "type": "noul", "instructions": "Kept"},
            ],
            set(),
        )
        self.assertEqual([row["id"] for row in rows], ["q"])

    def test_non_list_input_returns_nothing(self) -> None:
        self.assertEqual(normalize_generated_questions({"id": "q"}, set()), [])


if __name__ == "__main__":
    unittest.main()
