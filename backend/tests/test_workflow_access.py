"""Tests for the shared workflow access clause."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.exc import MultipleResultsFound

from app.db.models import Workflow
from app.services.workflow_access import user_has_workflow_access, workflow_access_clause


class WorkflowAccessClauseTest(unittest.TestCase):
    def test_clause_covers_owner_user_share_and_team_share(self) -> None:
        user_id = uuid.uuid4()
        sql = str(select(Workflow.id).where(workflow_access_clause(user_id)))

        self.assertIn("workflows.owner_id", sql)
        self.assertIn("workflow_shares", sql)
        self.assertIn("workflow_team_shares", sql)
        self.assertIn("team_members", sql)

    def test_clause_is_an_or_of_three_branches(self) -> None:
        user_id = uuid.uuid4()
        clause = workflow_access_clause(user_id)

        self.assertEqual(len(clause.clauses), 3)


class UserHasWorkflowAccessTest(unittest.IsolatedAsyncioTestCase):
    """Regression for the MultipleResultsFound follow-up on GHSA-pwr6-6377-3cgv.

    The previous implementation joined ``WorkflowTeamShare`` to ``TeamMember`` directly and
    called ``scalar_one_or_none()`` on the result. A user reachable through two teams that
    both share the workflow then produced two joined rows, and ``scalar_one_or_none()``
    raises ``MultipleResultsFound`` rather than returning a bool. Since a
    ``_revoke_execution_tokens_without_access`` pass checks every token holder on a workflow,
    this could turn an unrelated user's team memberships into a failed share removal.
    """

    async def test_non_owner_check_is_a_single_subquery_style_query(self) -> None:
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: workflow.id))

        result = await user_has_workflow_access(db, workflow, uuid.uuid4())

        self.assertTrue(result)
        # The old code issued a second db.execute() for the team-share join; the fixed
        # version answers from workflow_access_clause's IN-subqueries in one query, so it
        # can only ever match the single workflow.id row no matter how many teams apply.
        db.execute.assert_awaited_once()
        sql = str(db.execute.await_args.args[0]).upper()
        self.assertNotIn(" JOIN ", sql)

    async def test_owner_short_circuits_without_a_query(self) -> None:
        owner_id = uuid.uuid4()
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=owner_id)
        db = AsyncMock()

        result = await user_has_workflow_access(db, workflow, owner_id)

        self.assertTrue(result)
        db.execute.assert_not_awaited()

    async def test_user_with_no_path_to_the_workflow_is_denied(self) -> None:
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None))

        result = await user_has_workflow_access(db, workflow, uuid.uuid4())

        self.assertFalse(result)


class _CardinalityAwareResult:
    """A stand-in for SQLAlchemy's real ``Result``, not the usual
    ``SimpleNamespace(scalar_one_or_none=lambda: ...)`` double used above.

    Those doubles always hand back one canned value no matter which query ran, so they
    cannot fail against a join that fans out to two rows. This one actually enforces
    SQLAlchemy's row-count contract: ``scalar_one_or_none()`` raises
    ``MultipleResultsFound`` when given more than one row, exactly as a real session would
    for a join that matched twice. That is what makes the regression test below meaningful.
    """

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalar_one_or_none(self):
        if len(self._rows) > 1:
            raise MultipleResultsFound(
                f"Multiple rows were found when one was required: {len(self._rows)}"
            )
        return self._rows[0] if self._rows else None


async def _pre_fix_user_has_workflow_access(db, workflow, user_id: uuid.UUID) -> bool:
    """The implementation this regression test guards against, recreated verbatim.

    ``app.services.workflow_access`` no longer contains this shape; it is kept only here so
    the test can drive it directly and show it raises for a user reachable through two
    teams, which a canned-value mock could never demonstrate.
    """
    from app.db.models import TeamMember, WorkflowShare, WorkflowTeamShare

    if workflow.owner_id == user_id:
        return True
    share_result = await db.execute(
        select(WorkflowShare).where(
            WorkflowShare.workflow_id == workflow.id,
            WorkflowShare.user_id == user_id,
        )
    )
    if share_result.scalar_one_or_none() is not None:
        return True
    team_share_result = await db.execute(
        select(WorkflowTeamShare)
        .join(TeamMember, TeamMember.team_id == WorkflowTeamShare.team_id)
        .where(
            WorkflowTeamShare.workflow_id == workflow.id,
            TeamMember.user_id == user_id,
        )
    )
    return team_share_result.scalar_one_or_none() is not None


def _fake_multi_team_execute(stmt) -> _CardinalityAwareResult:
    """Answer a query by its actual compiled shape, not by call order.

    Modelled database state: a user who is not the owner, holds no direct share, and
    belongs to two teams that both share the workflow - the exact state a real database
    would hold for this regression. Discriminating by shape rather than by which call came
    first means the same fake evaluates the pre-fix implementation (two separate queries,
    the second of which is a join that fans out to two rows) and the fixed one (a single
    query over ``workflows`` with ``IN`` subqueries) each on their own real behavior.
    """
    sql = str(stmt)
    # The fixed query's own text also contains "FROM workflow_shares", inside its nested
    # subquery, so it is matched first by its outer SELECT rather than by substring alone.
    if sql.startswith("SELECT workflows.id"):
        return _CardinalityAwareResult(["the-workflow-row"])
    if "FROM workflow_team_shares JOIN" in sql:
        return _CardinalityAwareResult(["team-a-row", "team-b-row"])
    if sql.startswith("SELECT workflow_shares"):
        return _CardinalityAwareResult([])
    raise AssertionError(f"unrecognized query shape in test fake: {sql!r}")


class MultiTeamCardinalityRegressionTest(unittest.IsolatedAsyncioTestCase):
    """Runs the identical two-team database state through both implementations.

    Because ``db.execute`` answers by the query's shape rather than by call order, this
    would also fail if ``user_has_workflow_access`` were ever reverted to the join-based
    shape, not only when the recreated pre-fix implementation is invoked directly below.
    """

    async def test_pre_fix_implementation_raises_for_a_user_in_two_shared_teams(self) -> None:
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_fake_multi_team_execute)

        with self.assertRaises(MultipleResultsFound):
            await _pre_fix_user_has_workflow_access(db, workflow, uuid.uuid4())

    async def test_fixed_implementation_does_not_raise_for_the_same_database_state(
        self,
    ) -> None:
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_fake_multi_team_execute)

        result = await user_has_workflow_access(db, workflow, uuid.uuid4())

        self.assertTrue(result)
