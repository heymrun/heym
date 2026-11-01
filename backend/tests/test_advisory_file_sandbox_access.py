"""File sandbox access stays inside the one Drive rule, against real PostgreSQL.

Chat may open every Drive file its actor reaches: files they own and files shared
with a team they belong to. A workflow run may open only its own files (uploaded
to the workflow or written by its nodes) or the one Chat handed it. Nothing else,
whatever id or name a model, a prompt or an input supplies. These tests run the
real queries, plus mutation checks that loosening the team filter or dropping the
run scope makes the refusals fail, so the tests are known to be able to fail.

Requires a reachable PostgreSQL instance with migrations applied (see AGENTS.md,
"PostgreSQL Integration Tests").
"""

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import delete, literal, select, union_all

from app.db.models import FileTeamShare, GeneratedFile, Team, TeamMember, User, Workflow
from app.db.session import SessionLocal
from app.services.drive_file_access import GRANT_OWNER, GRANT_SHARED
from app.services.file_sandbox import manifest
from app.services.file_sandbox.detect import agent_input_toolbox
from app.services.file_sandbox.manifest import (
    FileAccessError,
    list_accessible_files,
    resolve_files,
    still_accessible,
)
from app.services.file_sandbox.scope import RunFileScope
from app.services.file_sandbox.tools import FileToolbox
from app.services.file_sandbox.workspace import FileWorkspace


def _loose_access_rows(user_id: uuid.UUID):  # noqa: ANN202 - mutation stand-in
    """The rule with the team-membership filter removed: every share counts."""
    return union_all(
        select(GeneratedFile.id.label("file_id"), literal(GRANT_OWNER).label("grant")).where(
            GeneratedFile.owner_id == user_id
        ),
        select(FileTeamShare.file_id.label("file_id"), literal(GRANT_SHARED).label("grant")),
    )


class RealPostgresFileSandboxAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = Path(self._tmp.name)
        self.owner = uuid.uuid4()
        self.teammate = uuid.uuid4()
        self.other_team_member = uuid.uuid4()
        self.outsider = uuid.uuid4()
        self.team = uuid.uuid4()
        self.other_team = uuid.uuid4()
        self.private_file = uuid.uuid4()
        self.shared_file = uuid.uuid4()
        self.workflow = uuid.uuid4()
        self.other_workflow = uuid.uuid4()
        self.upload_file = uuid.uuid4()
        self.other_upload_file = uuid.uuid4()
        self.files = [self.private_file, self.shared_file, self.upload_file, self.other_upload_file]
        users = [self.owner, self.teammate, self.other_team_member, self.outsider]
        self.users = users

        with SessionLocal() as db:
            for user_id in users:
                db.add(
                    User(
                        id=user_id,
                        email=f"fs_{user_id.hex[:10]}@example.com",
                        hashed_password="x",
                        name="U",
                    )
                )
            db.flush()
            db.add(Team(id=self.team, name="Finance", creator_id=self.owner))
            db.add(Team(id=self.other_team, name="Sales", creator_id=self.owner))
            db.flush()
            db.add(TeamMember(id=uuid.uuid4(), team_id=self.team, user_id=self.teammate))
            db.add(
                TeamMember(id=uuid.uuid4(), team_id=self.other_team, user_id=self.other_team_member)
            )
            for workflow_id in (self.workflow, self.other_workflow):
                db.add(Workflow(id=workflow_id, name="wf", owner_id=self.owner, nodes=[], edges=[]))
            db.flush()
            for file_id, name, workflow_id in (
                (self.private_file, "salaries.xlsx", None),
                (self.shared_file, "q3.xlsx", None),
                (self.upload_file, "invoice.pdf", self.workflow),
                (self.other_upload_file, "contract.pdf", self.other_workflow),
            ):
                relative = f"{self.owner}/{file_id}/{name}"
                disk = self.storage / relative
                disk.parent.mkdir(parents=True, exist_ok=True)
                disk.write_bytes(b"data")
                db.add(
                    GeneratedFile(
                        id=file_id,
                        owner_id=self.owner,
                        workflow_id=workflow_id,
                        filename=name,
                        storage_path=relative,
                        mime_type="application/vnd.ms-excel",
                        size_bytes=4,
                        metadata_json={},
                    )
                )
            db.flush()
            db.add(FileTeamShare(id=uuid.uuid4(), file_id=self.shared_file, team_id=self.team))
            db.commit()

        self._path_patch = patch.object(
            manifest, "get_file_path", side_effect=lambda row: self.storage / row.storage_path
        )
        self._path_patch.start()

    def tearDown(self) -> None:
        self._path_patch.stop()
        with SessionLocal() as db:
            files = self.files
            db.execute(delete(FileTeamShare).where(FileTeamShare.file_id.in_(files)))
            db.execute(delete(GeneratedFile).where(GeneratedFile.id.in_(files)))
            db.execute(
                delete(Workflow).where(Workflow.id.in_([self.workflow, self.other_workflow]))
            )
            db.execute(
                delete(TeamMember).where(TeamMember.team_id.in_([self.team, self.other_team]))
            )
            db.execute(delete(Team).where(Team.id.in_([self.team, self.other_team])))
            db.execute(delete(User).where(User.id.in_(self.users)))
            db.commit()
        self._tmp.cleanup()

    def _resolve(self, user_id: uuid.UUID, ref: str) -> list:
        with SessionLocal() as db:
            return resolve_files(db, user_id, [ref])

    def test_owner_reaches_own_files_by_id_and_name(self) -> None:
        self.assertEqual(self._resolve(self.owner, str(self.private_file))[0].id, self.private_file)
        self.assertEqual(self._resolve(self.owner, "salaries.xlsx")[0].id, self.private_file)

    def test_teammate_reaches_the_team_share(self) -> None:
        ref = self._resolve(self.teammate, str(self.shared_file))[0]
        self.assertTrue(ref.shared)

    def test_outsider_cannot_reach_a_private_file_by_id_or_name(self) -> None:
        for ref in (str(self.private_file), "salaries.xlsx"):
            with self.assertRaises(FileAccessError):
                self._resolve(self.outsider, ref)

    def test_teammate_cannot_reach_the_owners_unshared_file(self) -> None:
        with self.assertRaises(FileAccessError):
            self._resolve(self.teammate, str(self.private_file))

    def test_member_of_another_team_cannot_reach_the_share(self) -> None:
        with self.assertRaises(FileAccessError):
            self._resolve(self.other_team_member, str(self.shared_file))

    def test_loosened_rule_would_leak_the_share(self) -> None:
        """Mutation check: the cross-team refusal comes from the team filter."""
        with patch.object(manifest, "drive_file_access_rows", side_effect=_loose_access_rows):
            ref = self._resolve(self.other_team_member, str(self.shared_file))[0]
        self.assertEqual(ref.id, self.shared_file)

    def test_missing_and_foreign_ids_fail_with_the_same_message(self) -> None:
        with self.assertRaises(FileAccessError) as foreign:
            self._resolve(self.outsider, str(self.private_file))
        missing = uuid.uuid4()
        with self.assertRaises(FileAccessError) as absent:
            self._resolve(self.outsider, str(missing))
        self.assertEqual(
            str(foreign.exception).replace(str(self.private_file), "<id>"),
            str(absent.exception).replace(str(missing), "<id>"),
        )

    def test_revoked_share_and_removed_membership_drop_access(self) -> None:
        with SessionLocal() as db:
            self.assertEqual(
                still_accessible(db, self.teammate, {self.shared_file}), {self.shared_file}
            )
            db.execute(delete(FileTeamShare).where(FileTeamShare.file_id == self.shared_file))
            db.commit()
            self.assertEqual(still_accessible(db, self.teammate, {self.shared_file}), set())
        with self.assertRaises(FileAccessError):
            self._resolve(self.teammate, str(self.shared_file))

    def test_removed_membership_drops_access(self) -> None:
        with SessionLocal() as db:
            db.execute(delete(TeamMember).where(TeamMember.user_id == self.teammate))
            db.commit()
            self.assertEqual(still_accessible(db, self.teammate, {self.shared_file}), set())

    def test_listing_shows_only_reachable_files_and_no_paths_or_tokens(self) -> None:
        with SessionLocal() as db:
            outsider_refs, outsider_total = list_accessible_files(db, self.outsider)
            teammate_refs, _ = list_accessible_files(db, self.teammate)
        self.assertEqual((outsider_refs, outsider_total), ([], 0))
        self.assertEqual([r.id for r in teammate_refs], [self.shared_file])
        public = teammate_refs[0].public()
        self.assertEqual(
            set(public), {"id", "name", "mime", "size", "created_at", "source", "shared"}
        )
        self.assertNotIn(str(self.storage), str(public))

    def test_toolbox_refuses_and_copies_nothing_for_a_foreign_file(self) -> None:
        workspace = FileWorkspace(self.storage / "ws", owner_id=self.outsider)
        toolbox = FileToolbox(workspace, self.outsider, source_label="Chat")
        with patch("app.services.file_sandbox.tools.run_in_sandbox") as run:
            result = toolbox.call("inspect_file", {"file": str(self.private_file)})
        run.assert_not_called()
        self.assertIn("not found or not accessible", result["error"])
        self.assertEqual(workspace.inputs(), [])

    def test_toolbox_prunes_a_copy_after_revocation(self) -> None:
        workspace = FileWorkspace(self.storage / "ws2", owner_id=self.teammate)
        toolbox = FileToolbox(workspace, self.teammate, source_label="Chat")
        outcome = unittest.mock.Mock(success=True, result={}, error=None, stdout="")
        outcome.stdout_dropped_chars = 0
        with patch("app.services.file_sandbox.tools.run_in_sandbox", return_value=outcome):
            toolbox.call("inspect_file", {"file": str(self.shared_file)})
            self.assertEqual(workspace.input_ids(), {self.shared_file})
            with SessionLocal() as db:
                db.execute(delete(FileTeamShare).where(FileTeamShare.file_id == self.shared_file))
                db.commit()
            result = toolbox.call("run_python", {"code": "print(1)"})
        self.assertEqual(workspace.input_ids(), set())
        self.assertEqual(result["removed_inputs"], ["q3.xlsx"])
        workspace.delete()

    def _run_scope(self) -> RunFileScope:
        return RunFileScope().including_workflow(self.workflow)

    def _agent_toolbox(
        self, actor: uuid.UUID, *file_ids: uuid.UUID, scope: RunFileScope | None = None
    ) -> FileToolbox | None:
        inputs = {"Upload": {"files": [{"id": str(file_id)} for file_id in file_ids]}}
        with patch("app.services.file_sandbox.workspace.sandbox_root", return_value=self.storage):
            return agent_input_toolbox(
                (inputs,),
                actor,
                scope=scope or self._run_scope(),
                source_label="Agent",
                workflow_id=self.workflow,
            )

    def test_run_agent_opens_a_file_uploaded_to_its_workflow(self) -> None:
        toolbox = self._agent_toolbox(self.owner, self.upload_file)
        self.assertEqual([ref.id for ref in toolbox.input_files], [self.upload_file])

    def test_a_drive_id_in_a_run_opens_nothing_even_for_the_owner(self) -> None:
        """Point of the run scope: a workflow cannot be used to read its actor's Drive."""
        self.assertIsNone(self._agent_toolbox(self.owner, self.private_file))
        self.assertIsNone(self._agent_toolbox(self.owner, self.other_upload_file))
        self.assertIsNone(self._agent_toolbox(self.teammate, self.shared_file))

    def test_dropping_the_run_scope_would_open_the_owners_drive(self) -> None:
        """Mutation check: the refusal above comes from the run scope."""
        with SessionLocal() as db:
            unscoped = resolve_files(db, self.owner, [str(self.private_file)])
        self.assertEqual(unscoped[0].id, self.private_file)

    def test_run_toolbox_lists_and_opens_only_its_input_files(self) -> None:
        toolbox = self._agent_toolbox(self.owner, self.upload_file, self.private_file)
        self.assertEqual([ref.id for ref in toolbox.input_files], [self.upload_file])
        listed = toolbox.call("list_files", {})
        self.assertEqual([item["id"] for item in listed["files"]], [str(self.upload_file)])
        self.assertEqual(listed["total"], 1)
        with patch("app.services.file_sandbox.tools.run_in_sandbox") as run:
            for ref in (str(self.private_file), "salaries.xlsx", str(self.other_upload_file)):
                result = toolbox.call("inspect_file", {"file": ref})
                self.assertIn("not found or not accessible", result["error"])
        run.assert_not_called()
        self.assertEqual(toolbox.workspace.inputs(), [])
        toolbox.workspace.delete()

    def test_the_run_scope_keeps_the_access_rule(self) -> None:
        scope = RunFileScope(file_ids=frozenset({self.private_file, self.shared_file}))
        self.assertIsNone(self._agent_toolbox(self.outsider, self.private_file, scope=scope))
        self.assertIsNone(
            self._agent_toolbox(self.other_team_member, self.shared_file, scope=scope)
        )
        teammate = self._agent_toolbox(
            self.teammate, self.private_file, self.shared_file, scope=scope
        )
        self.assertEqual([ref.id for ref in teammate.input_files], [self.shared_file])

    def test_a_file_chat_handed_to_the_run_opens(self) -> None:
        scope = self._run_scope()
        chat_scope = RunFileScope(
            workflow_ids=scope.workflow_ids, file_ids=frozenset({self.private_file})
        )
        toolbox = self._agent_toolbox(self.owner, self.private_file, scope=chat_scope)
        self.assertEqual([ref.id for ref in toolbox.input_files], [self.private_file])

    def test_a_sub_workflow_opens_its_parents_files(self) -> None:
        scope = self._run_scope().including_workflow(self.other_workflow)
        toolbox = self._agent_toolbox(
            self.owner, self.upload_file, self.other_upload_file, scope=scope
        )
        self.assertEqual(
            {ref.id for ref in toolbox.input_files}, {self.upload_file, self.other_upload_file}
        )

    def test_code_node_resolution_stays_in_the_run_scope(self) -> None:
        scope = self._run_scope()
        with SessionLocal() as db:
            self.assertEqual(
                resolve_files(db, self.owner, [str(self.upload_file)], scope=scope)[0].id,
                self.upload_file,
            )
            for ref in (str(self.private_file), "salaries.xlsx", str(self.other_upload_file)):
                with self.assertRaises(FileAccessError):
                    resolve_files(db, self.owner, [ref], scope=scope)

    def test_loosened_rule_would_turn_tools_on_for_a_foreign_file(self) -> None:
        """Mutation check: the agent-input refusal comes from the same team filter."""
        scope = RunFileScope(file_ids=frozenset({self.shared_file}))
        with patch.object(manifest, "drive_file_access_rows", side_effect=_loose_access_rows):
            toolbox = self._agent_toolbox(self.other_team_member, self.shared_file, scope=scope)
        self.assertEqual([ref.id for ref in toolbox.input_files], [self.shared_file])


if __name__ == "__main__":
    unittest.main()
