"""Placing a skill on a workflow: match updates, a new name adds, ambiguity does not save."""

import unittest

from app.services.skill_apply import FileEdit, new_skill_workflow, place_skill
from app.services.skill_archive import ArchiveFile, SkillBundle

BUNDLE = SkillBundle(
    name="invoice-helper",
    content="Read the invoice.",
    files=(ArchiveFile("main.py", "def run():\n    return 1\n"),),
    directory="helper",
)


def _agent(agent_id: str, label: str, skills: list[dict] | None = None) -> dict:
    return {
        "id": agent_id,
        "type": "agent",
        "data": {"label": label, "skills": skills or [], "credentialId": "cred-1"},
    }


class PlaceSkillTests(unittest.TestCase):
    def test_the_same_name_updates_that_skill_and_keeps_the_other(self) -> None:
        nodes = [
            _agent(
                "a1",
                "Clerk",
                [
                    {
                        "id": "s1",
                        "name": "invoice-helper",
                        "content": "old",
                        "files": [
                            {"path": "main.py", "content": "old", "encoding": "text"},
                            {"path": "logo.png", "content": "abc", "encoding": "base64"},
                        ],
                        "timeoutSeconds": 15,
                    },
                    {"id": "s2", "name": "other", "content": "stay", "files": []},
                ],
            )
        ]

        placed = place_skill(nodes, BUNDLE)

        self.assertEqual(placed.status, "saved")
        skills = placed.nodes[0]["data"]["skills"]
        self.assertEqual(skills[0]["content"], "Read the invoice.")
        self.assertEqual(skills[0]["id"], "s1")
        self.assertEqual(skills[0]["timeoutSeconds"], 15)
        self.assertEqual(
            skills[0]["files"][0], {"path": "logo.png", "content": "abc", "encoding": "base64"}
        )
        self.assertEqual(skills[0]["files"][1]["content"], "def run():\n    return 1\n")
        self.assertEqual(skills[1]["name"], "other")
        self.assertEqual(nodes[0]["data"]["skills"][0]["content"], "old")

    def test_a_new_name_is_added_to_the_only_agent(self) -> None:
        nodes = [
            _agent("a1", "Clerk", [{"id": "s2", "name": "other", "content": "stay", "files": []}])
        ]

        placed = place_skill(nodes, BUNDLE)

        self.assertEqual(placed.status, "saved")
        self.assertEqual(
            [skill["name"] for skill in placed.nodes[0]["data"]["skills"]],
            ["other", "invoice-helper"],
        )

    def test_several_agents_and_a_new_skill_need_a_choice(self) -> None:
        nodes = [_agent("a1", "Clerk"), _agent("a2", "Reviewer")]

        placed = place_skill(nodes, BUNDLE)

        self.assertEqual(placed.status, "needs_choice")
        self.assertEqual([agent["id"] for agent in placed.agents], ["a1", "a2"])
        self.assertIsNone(placed.nodes)

    def test_an_agent_id_adds_the_skill_there(self) -> None:
        nodes = [_agent("a1", "Clerk"), _agent("a2", "Reviewer")]

        placed = place_skill(nodes, BUNDLE, agent_id="a2")

        self.assertEqual(placed.status, "saved")
        self.assertEqual(placed.nodes[0]["data"]["skills"], [])
        self.assertEqual(placed.nodes[1]["data"]["skills"][0]["name"], "invoice-helper")

    def test_a_file_edit_changes_only_the_named_file(self) -> None:
        nodes = [
            _agent(
                "a1",
                "Clerk",
                [
                    {
                        "id": "s1",
                        "name": "invoice-helper",
                        "content": "old",
                        "files": [
                            {
                                "path": "main.py",
                                "content": "def run():\n    return 1\n",
                                "encoding": "text",
                            }
                        ],
                    }
                ],
            )
        ]

        placed = place_skill(
            nodes,
            None,
            skill_name="invoice-helper",
            edits=[FileEdit("SKILL.md", "Read it carefully.")],
        )

        skill = placed.nodes[0]["data"]["skills"][0]
        self.assertEqual(skill["content"], "Read it carefully.")
        self.assertEqual(skill["files"][0]["content"], "def run():\n    return 1\n")

    def test_a_new_workflow_is_one_agent_with_the_skill(self) -> None:
        name, nodes, edges = new_skill_workflow(BUNDLE, "cred-1", "gpt-4o")

        self.assertEqual(name, "invoice-helper")
        self.assertEqual([node["type"] for node in nodes], ["textInput", "agent", "output"])
        self.assertEqual(nodes[1]["data"]["skills"][0]["name"], "invoice-helper")
        self.assertEqual(nodes[1]["data"]["credentialId"], "cred-1")
        self.assertEqual(nodes[1]["data"]["model"], "gpt-4o")
        self.assertEqual([edge["source"] for edge in edges], ["request", "agent"])


if __name__ == "__main__":
    unittest.main()
