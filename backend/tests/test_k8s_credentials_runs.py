"""Secret-backed credentials in the API, in runs, in dispatch and in settings."""

from __future__ import annotations

import asyncio
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from asyncpg import CannotConnectNowError, PostgresConnectionError
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from app.api.credentials import display_config, refuse_secret_backed
from app.config import Settings
from app.db.models import ClusterInstance, CredentialType
from app.db.session import async_session_maker, engine
from app.services.cluster import registry
from app.services.cluster.dispatch import RunQueueWorker
from app.services.credential_context import CredentialsContext, unavailable_credential_error
from app.services.encryption import encrypt_config
from app.services.k8s_credentials.store import SecretCredential, SecretCredentialStore
from app.services.workflow_executor import execute_workflow

POINTER = "k8s:heym/heym-cred-llm"


def _credential(**over: object) -> SimpleNamespace:
    fields: dict = dict(
        id=uuid.uuid4(),
        name="llm",
        type=CredentialType.openai,
        source=POINTER,
        encrypted_config=POINTER,
    )
    fields.update(over)
    return SimpleNamespace(**fields)


def _synced_store(config: dict | None) -> SecretCredentialStore:
    store = SecretCredentialStore()
    store.enabled = True
    items = []
    if config is not None:
        items.append(
            SecretCredential(
                namespace="heym",
                secret_name="heym-cred-llm",
                name="llm",
                type="openai",
                owner_email="a@example.com",
                config=config,
            )
        )
    store.replace_all(items)
    return store


class DisplayTests(unittest.TestCase):
    def test_a_secret_backed_credential_shows_its_secret_not_a_value_prefix(self) -> None:
        with patch(
            "app.services.encryption.k8s_credential_store",
            _synced_store({"api_key": "sk-secretvalue"}),
        ):
            config, masked, _ = display_config(_credential())  # type: ignore[arg-type]

        self.assertEqual(masked, POINTER)
        self.assertNotIn("sk-secr", masked or "")
        self.assertEqual(config, {"api_key": "sk-secretvalue"})

    def test_an_unavailable_one_still_lists(self) -> None:
        """One deleted Secret must not turn the whole credentials page into a 500."""
        with patch("app.services.encryption.k8s_credential_store", _synced_store(None)):
            config, masked, _ = display_config(_credential())  # type: ignore[arg-type]

        self.assertEqual((config, masked), ({}, POINTER))

    def test_ui_credentials_keep_their_mask(self) -> None:
        ui = _credential(source=None, encrypted_config=encrypt_config({"api_key": "sk-1234567890"}))

        _, masked, _ = display_config(ui)  # type: ignore[arg-type]

        self.assertEqual(masked, "sk-1234**")

    def test_changes_are_refused_with_409_naming_the_secret(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            refuse_secret_backed(_credential())  # type: ignore[arg-type]

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("heym/heym-cred-llm", str(ctx.exception.detail))
        refuse_secret_backed(_credential(source=None))  # type: ignore[arg-type]


class RunEntryTests(unittest.TestCase):
    def _context(self) -> CredentialsContext:
        context = CredentialsContext({"other": "x"})
        context.unavailable["llm"] = "Kubernetes credential unavailable: not synced yet"
        return context

    def test_a_run_that_references_it_is_refused_before_any_node_runs(self) -> None:
        nodes = [{"id": "n1", "data": {"url": "$credentials.llm"}}]

        with patch("app.services.workflow_executor.WorkflowExecutor") as executor:
            result = execute_workflow(
                uuid.uuid4(), nodes, [], {}, credentials_context=self._context()
            )

        executor.assert_not_called()
        self.assertEqual(result.status, "error")
        self.assertIn('credential "llm"', result.outputs["error"])

    def test_every_reference_form_counts(self) -> None:
        for expression in ("$credentials.llm", '$credentials["llm"]', "$credentials['llm']"):
            with self.subTest(expression):
                nodes = [{"data": {"headers": [{"value": expression}]}}]
                self.assertIsNotNone(unavailable_credential_error(self._context(), nodes))

    def test_a_longer_name_that_starts_with_it_doesnt_count(self) -> None:
        for expression in (
            "$credentials.llm_v2",
            "$credentials.llm2",
            '$credentials["llm_v2"]',
            "$credentials['llm2']",
        ):
            with self.subTest(expression):
                nodes = [{"data": {"url": expression}}]
                self.assertIsNone(unavailable_credential_error(self._context(), nodes))

    def test_a_field_of_it_or_it_inside_an_expression_counts(self) -> None:
        for expression in (
            "$credentials.llm.api_key",
            "{{ $credentials.llm }}",
            "$credentials.llm,$credentials.other",
        ):
            with self.subTest(expression):
                nodes = [{"data": {"url": expression}}]
                self.assertIsNotNone(unavailable_credential_error(self._context(), nodes))

    def test_a_name_with_regex_characters_is_matched_literally(self) -> None:
        context = CredentialsContext()
        context.unavailable["a.b+"] = "not synced yet"

        self.assertIsNotNone(
            unavailable_credential_error(context, [{"data": {"url": '$credentials["a.b+"]'}}])
        )
        self.assertIsNone(
            unavailable_credential_error(context, [{"data": {"url": '$credentials["aXbb"]'}}])
        )

    def test_a_reference_inside_a_sub_workflow_counts(self) -> None:
        cache = {"sub": {"nodes": [{"data": {"prompt": "use $credentials.llm"}}]}}

        self.assertIsNotNone(unavailable_credential_error(self._context(), [], cache))

    def test_a_run_that_doesnt_use_it_goes_ahead(self) -> None:
        nodes = [{"data": {"url": "$credentials.other"}}]

        self.assertIsNone(unavailable_credential_error(self._context(), nodes))
        self.assertIsNone(unavailable_credential_error({"llm": "x"}, nodes))


class ContextTests(IsolatedAsyncioTestCase):
    async def test_an_unsynced_secret_backed_credential_is_recorded_not_dropped(self) -> None:
        from app.api.workflows import get_credentials_context

        unsynced = SecretCredentialStore()
        unsynced.enabled = True
        ui = _credential(name="ui", source=None, encrypted_config=encrypt_config({"api_key": "k"}))
        db = AsyncMock()
        owned = MagicMock()
        owned.scalars.return_value.all.return_value = [_credential(), ui]
        empty = MagicMock()
        empty.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[owned, empty, empty])

        with patch("app.services.encryption.k8s_credential_store", unsynced):
            context = await get_credentials_context(db, uuid.uuid4())

        self.assertEqual(dict(context), {"ui": "k"})
        self.assertIn("not synced from Kubernetes yet", context.unavailable["llm"])


class SettingsTests(unittest.TestCase):
    def test_subprocess_sandboxes_are_refused_with_the_feature_on(self) -> None:
        with patch.dict(
            os.environ, {"HEYM_K8S_CREDENTIALS": "true", "HEYM_PYTHON_TOOL_SANDBOX": "subprocess"}
        ):
            with self.assertRaisesRegex(ValidationError, "HEYM_PYTHON_TOOL_SANDBOX=subprocess"):
                Settings()

    def test_subprocess_is_fine_with_the_feature_off(self) -> None:
        with patch.dict(
            os.environ, {"HEYM_K8S_CREDENTIALS": "false", "HEYM_PLAYWRIGHT_SANDBOX": "subprocess"}
        ):
            Settings()


class ClaimGateTests(IsolatedAsyncioTestCase):
    async def _run_loop_once(self, store: SecretCredentialStore) -> AsyncMock:
        worker = RunQueueWorker()
        worker._running = True
        waits = {"n": 0}

        async def wait_for_work() -> None:
            waits["n"] += 1
            if waits["n"] > 1:
                worker._running = False

        bus = SimpleNamespace(wait_for_work=wait_for_work)
        claim = AsyncMock(return_value=None)
        with (
            patch("app.services.cluster.dispatch.k8s_credential_store", store),
            patch("app.services.cluster.dispatch.run_queue.claim_next", claim),
        ):
            await worker._run_loop(bus)
        return claim

    async def test_an_unsynced_process_claims_nothing(self) -> None:
        unsynced = SecretCredentialStore()
        unsynced.enabled = True

        claim = await self._run_loop_once(unsynced)

        claim.assert_not_called()

    async def test_a_synced_process_claims(self) -> None:
        claim = await self._run_loop_once(_synced_store(None))

        claim.assert_awaited()


class DispatchTests(unittest.TestCase):
    def _view(self, synced_at: datetime | None) -> registry.InstanceView:
        now = datetime.now(timezone.utc)
        return registry.InstanceView(
            id="w1",
            name="w1",
            role="worker",
            enabled=True,
            weight=50,
            weight_configured=True,
            version="1",
            schema_revision="r",
            keys_fingerprint="k",
            docker_ok=True,
            db_latency_ms=1.0,
            heartbeat_at=now,
            credentials_synced_at=synced_at,
        )

    def test_an_instance_is_synced_only_while_a_synced_process_beats(self) -> None:
        now = datetime.now(timezone.utc)
        stale = now - timedelta(seconds=registry.LIVENESS_WINDOW_SECONDS + 1)

        self.assertTrue(registry.credentials_synced(self._view(now), now=now))
        self.assertFalse(registry.credentials_synced(self._view(None), now=now))
        self.assertFalse(registry.credentials_synced(self._view(stale), now=now))

    def test_an_unsynced_instance_gets_no_work(self) -> None:
        now = datetime.now(timezone.utc)
        main = SimpleNamespace(**{**vars(self._view(now)), "id": "main", "role": "main"})
        main = registry.InstanceView(**vars(main))

        pool = registry.candidate_instances([main, self._view(None)], now=now)

        self.assertEqual([i.id for i in pool], ["main"])


class HeartbeatPostgresTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        try:
            async with asyncio.timeout(10):
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        except (OSError, TimeoutError, PostgresConnectionError, CannotConnectNowError) as exc:
            await engine.dispose()
            self.skipTest(f"PostgreSQL is unavailable ({type(exc).__name__})")
        except DBAPIError as exc:
            if not exc.connection_invalidated:
                raise
            await engine.dispose()
            self.skipTest("PostgreSQL connection is unavailable")
        self.instance_id = f"k8s-sync-{uuid.uuid4().hex[:10]}"

    async def asyncTearDown(self) -> None:
        async with async_session_maker() as db:
            await db.execute(delete(ClusterInstance).where(ClusterInstance.id == self.instance_id))
            await db.commit()
        await engine.dispose()

    async def _beat(self, store: SecretCredentialStore) -> datetime | None:
        with (
            patch(
                "app.services.cluster.registry.identity.instance_id", return_value=self.instance_id
            ),
            patch("app.services.cluster.registry.k8s_credential_store", store),
            patch("app.services.cluster.registry._sandbox_reachable", return_value=True),
        ):
            await registry.write_heartbeat()
        async with async_session_maker() as db:
            return (
                await db.execute(
                    select(ClusterInstance.credentials_synced_at).where(
                        ClusterInstance.id == self.instance_id
                    )
                )
            ).scalar_one()

    async def test_an_unsynced_sibling_never_clears_a_synced_beat(self) -> None:
        unsynced = SecretCredentialStore()
        unsynced.enabled = True

        self.assertIsNone(await self._beat(unsynced))
        synced_at = await self._beat(_synced_store(None))
        after_sibling = await self._beat(unsynced)

        self.assertIsNotNone(synced_at)
        self.assertEqual(after_sibling, synced_at)


if __name__ == "__main__":
    unittest.main()
