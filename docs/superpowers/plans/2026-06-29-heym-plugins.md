# Heym Plugins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add zip-installable plugins that act as custom workflow nodes (action/3rd-party + trigger), managed by an operator-admin, surfaced in the canvas palette, Settings dialog, `/documentation`, and the AI assistant prompt.

**Architecture:** Plugins are trusted, Heym-delivered code installed by an admin (gated by `HEYM_PLUGIN_ADMIN_EMAILS` + `HEYM_PLUGINS_ENABLED`). A plugin `.zip` carries a `plugin.json` manifest, a `handler.py`, a `README.md`, and an optional `icon.svg`. On install the zip is extracted to `HEYM_PLUGINS_DIR/<plugin_id>/`, declared pip `dependencies` are installed into the instance, and metadata is persisted in a `plugins` table. At runtime two static node types (`plugin`, `pluginTrigger`) dispatch to a single handler that dynamically imports the plugin's `handler.py` and calls `run()`/`trigger()` in-process (full trust, like a built-in node). Installed plugins are injected into `build_assistant_prompt(...)` (never the static synced `WORKFLOW_DSL_SYSTEM_PROMPT`).

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 async + Alembic + Pydantic (backend); Vue 3 + TypeScript strict + Pinia (frontend); pytest (unittest/IsolatedAsyncioTestCase + AsyncMock).

**Spec:** `docs/superpowers/specs/2026-06-29-heym-plugins-design.md`

---

## File Structure

**Backend — create:**
- `backend/app/models/plugin_schemas.py` — `PluginField`, `PluginManifest`, API response models.
- `backend/app/services/plugin_store.py` — install/uninstall/list on disk + DB; zip extraction, validation, dependency install.
- `backend/app/services/plugin_loader.py` — in-process dynamic import + manifest disk lookup + module cache.
- `backend/app/api/plugins.py` — router, gate deps, endpoints.
- `backend/app/services/node_execution/nodes/plugin_node.py` — action dispatcher handler.
- `backend/app/services/node_execution/nodes/plugin_trigger_node.py` — trigger dispatcher handler.
- `backend/alembic/versions/<rev>_add_plugins_table.py` — migration.
- Tests: `backend/tests/test_plugin_manifest.py`, `test_plugin_store.py`, `test_plugin_loader.py`, `test_plugins_api.py`, `test_plugin_node.py`, `test_plugin_dsl_prompt.py`.

**Backend — modify:**
- `backend/app/config.py` — new settings.
- `backend/app/db/models.py` — `Plugin` model.
- `backend/app/main.py` — register router.
- `backend/app/services/node_execution/registry.py` — register two node types.
- `backend/app/services/workflow_dsl_prompt.py` — `build_assistant_prompt` injection.

**Frontend — create:**
- `frontend/src/services/plugins.ts` — API client + types.
- `frontend/src/components/Panels/propertiesPanel/nodes/PluginNodeProperties.vue` — schema-driven config form.

**Frontend — modify:**
- `frontend/src/types/workflow.ts` — `NodeType` union + plugin node data.
- `frontend/src/components/Panels/NodePanel.vue` — palette section.
- `frontend/src/components/Panels/PropertiesPanel.vue` — route plugin types to the new component.
- `frontend/src/components/Layout/UserSettingsDialog.vue` — Plugins tab.
- `frontend/src/views/DocsView.vue` (+ docs loading) — dynamic Plugins category.

**Ops — modify:** `.env.example`, `docker-compose.yml`, `run.sh`, `deploy.sh`.

---

## Phase 1 — Backend Foundation

### Task 1: Config settings + manifest model

**Files:**
- Modify: `backend/app/config.py:64-65` (add after `docker_logs_allowed_emails`)
- Create: `backend/app/models/plugin_schemas.py`
- Test: `backend/tests/test_plugin_manifest.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_plugin_manifest.py`:

```python
import unittest

from pydantic import ValidationError

from app.models.plugin_schemas import PluginManifest


class PluginManifestTests(unittest.TestCase):
    def _valid(self) -> dict:
        return {
            "id": "acme-crm",
            "name": "Acme CRM",
            "version": "1.0.0",
            "kind": "action",
            "description": "Send records to Acme",
            "fields": [
                {"key": "apiKey", "label": "API Key", "type": "string", "secret": True, "required": True},
                {"key": "recordId", "label": "Record ID", "type": "string", "dynamic": True, "expression": True},
            ],
        }

    def test_parses_valid_manifest(self) -> None:
        manifest = PluginManifest.model_validate(self._valid())
        self.assertEqual(manifest.id, "acme-crm")
        self.assertEqual(manifest.kind, "action")
        self.assertEqual(manifest.entry, "handler.py")
        self.assertEqual(manifest.fields[0].key, "apiKey")
        self.assertTrue(manifest.fields[0].secret)

    def test_rejects_bad_id(self) -> None:
        bad = self._valid()
        bad["id"] = "Acme CRM!"
        with self.assertRaises(ValidationError):
            PluginManifest.model_validate(bad)

    def test_rejects_unknown_kind(self) -> None:
        bad = self._valid()
        bad["kind"] = "webhook"
        with self.assertRaises(ValidationError):
            PluginManifest.model_validate(bad)

    def test_defaults_optional_fields(self) -> None:
        minimal = {"id": "p1", "name": "P1", "version": "0.1.0", "kind": "trigger"}
        manifest = PluginManifest.model_validate(minimal)
        self.assertEqual(manifest.fields, [])
        self.assertEqual(manifest.dependencies, [])
        self.assertEqual(manifest.doc_slug, "p1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_plugin_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.plugin_schemas'`

- [ ] **Step 3: Write the manifest model**

Create `backend/app/models/plugin_schemas.py`:

```python
"""Pydantic models for plugin manifests and the plugins API."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_PLUGIN_ID_RE = re.compile(r"^[a-z0-9-]+$")

PluginKind = Literal["action", "trigger"]
PluginFieldType = Literal["string", "number", "boolean", "select"]


class PluginFieldOption(BaseModel):
    label: str
    value: str


class PluginField(BaseModel):
    key: str
    label: str
    type: PluginFieldType = "string"
    required: bool = False
    secret: bool = False
    default: str | float | bool | None = None
    options: list[PluginFieldOption] = Field(default_factory=list)
    dynamic: bool = False
    expression: bool = False


class PluginManifest(BaseModel):
    id: str
    name: str
    version: str
    kind: PluginKind
    description: str = ""
    entry: str = "handler.py"
    dependencies: list[str] = Field(default_factory=list)
    fields: list[PluginField] = Field(default_factory=list)
    dsl_hint: str = Field(default="", alias="dslHint")
    doc_slug: str = Field(default="", alias="docSlug")

    model_config = {"populate_by_name": True}

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not _PLUGIN_ID_RE.match(v):
            raise ValueError("Plugin id must match ^[a-z0-9-]+$")
        return v

    def resolved_doc_slug(self) -> str:
        return self.doc_slug or self.id


class PluginSummary(BaseModel):
    """Public listing shape returned by GET /api/plugins."""

    id: str
    name: str
    version: str
    kind: PluginKind
    description: str
    enabled: bool
    fields: list[PluginField]
    dsl_hint: str = ""
    doc_slug: str = ""
    has_icon: bool = False


class PluginDoc(BaseModel):
    id: str
    name: str
    doc_slug: str
    markdown: str
```

Note: `model_validator` defaulting `doc_slug` to `id` is handled in `resolved_doc_slug()` so the stored manifest keeps the raw value; the `test_defaults_optional_fields` asserts `doc_slug == "p1"` — update the model to default it. Replace the `doc_slug` field + add a model validator:

```python
    from pydantic import model_validator  # add to imports

    @model_validator(mode="after")
    def _default_doc_slug(self) -> "PluginManifest":
        if not self.doc_slug:
            object.__setattr__(self, "doc_slug", self.id)
        return self
```

- [ ] **Step 4: Add config settings**

In `backend/app/config.py`, after line 65 (`docker_logs_allowed_emails: str = ""`):

```python
    plugins_enabled: bool = Field(default=False, validation_alias="HEYM_PLUGINS_ENABLED")
    plugin_admin_emails: str = Field(default="", validation_alias="HEYM_PLUGIN_ADMIN_EMAILS")
    plugins_dir: str = Field(default="data/plugins", validation_alias="HEYM_PLUGINS_DIR")
```

(`Field` is already imported at `backend/app/config.py:3`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_plugin_manifest.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/plugin_schemas.py backend/app/config.py backend/tests/test_plugin_manifest.py
git commit -m "feat(plugins): manifest model + config settings"
```

---

### Task 2: `Plugin` DB model + migration

**Files:**
- Modify: `backend/app/db/models.py` (add `Plugin` class near other top-level models)
- Create: `backend/alembic/versions/<rev>_add_plugins_table.py`

- [ ] **Step 1: Add the model**

In `backend/app/db/models.py`, add (follow the existing import style already present in the file — `Mapped`, `mapped_column`, `String`, `Text`, `Boolean`, `JSONB`, `DateTime`, `func`, `uuid`, `datetime` are already imported):

```python
class Plugin(Base):
    __tablename__ = "plugins"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plugin_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    installed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 2: Generate the migration**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run alembic revision --autogenerate -m "add plugins table"`
Expected: a new file in `backend/alembic/versions/`. Open it and confirm `op.create_table("plugins", ...)` with the columns above and a unique index on `plugin_id`. If autogenerate misses the `JSONB`/index, edit to match:

```python
def upgrade() -> None:
    op.create_table(
        "plugins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plugin_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("installed_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_plugins_plugin_id", "plugins", ["plugin_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_plugins_plugin_id", table_name="plugins")
    op.drop_table("plugins")
```

- [ ] **Step 3: Apply the migration**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run alembic upgrade head`
Expected: `Running upgrade ... add plugins table`

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/
git commit -m "feat(plugins): plugins table model + migration"
```

---

### Task 3: Plugin store (install / uninstall / list on disk + DB)

**Files:**
- Create: `backend/app/services/plugin_store.py`
- Test: `backend/tests/test_plugin_store.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_plugin_store.py`:

```python
import io
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services import plugin_store
from app.services.plugin_store import PluginInstallError


def _make_zip(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


_VALID_MANIFEST = """{
  "id": "acme-crm", "name": "Acme CRM", "version": "1.0.0", "kind": "action",
  "description": "x", "fields": []
}"""
_HANDLER = "def run(inputs, config, ctx):\n    return {'ok': True}\n"


class PluginStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_extract_valid_plugin(self) -> None:
        data = _make_zip({"plugin.json": _VALID_MANIFEST, "handler.py": _HANDLER, "README.md": "# Acme"})
        with patch.object(plugin_store, "_install_dependencies") as deps:
            manifest = plugin_store.extract_and_validate(data, self.dir)
        self.assertEqual(manifest.id, "acme-crm")
        self.assertTrue((self.dir / "acme-crm" / "handler.py").exists())
        deps.assert_called_once()

    def test_rejects_zip_slip(self) -> None:
        data = _make_zip({"plugin.json": _VALID_MANIFEST, "../evil.py": "x"})
        with self.assertRaises(PluginInstallError):
            plugin_store.extract_and_validate(data, self.dir)
        self.assertFalse((self.dir.parent / "evil.py").exists())

    def test_rejects_missing_manifest(self) -> None:
        data = _make_zip({"handler.py": _HANDLER})
        with self.assertRaises(PluginInstallError):
            plugin_store.extract_and_validate(data, self.dir)

    def test_rejects_missing_handler(self) -> None:
        data = _make_zip({"plugin.json": _VALID_MANIFEST})
        with self.assertRaises(PluginInstallError):
            plugin_store.extract_and_validate(data, self.dir)

    def test_dependency_failure_rolls_back(self) -> None:
        manifest_with_deps = _VALID_MANIFEST.replace('"fields": []', '"fields": [], "dependencies": ["nonexistent-xyz"]')
        data = _make_zip({"plugin.json": manifest_with_deps, "handler.py": _HANDLER})
        with patch.object(plugin_store, "_install_dependencies", side_effect=PluginInstallError("pip failed")):
            with self.assertRaises(PluginInstallError):
                plugin_store.extract_and_validate(data, self.dir)
        self.assertFalse((self.dir / "acme-crm").exists())

    def test_remove_plugin_dir(self) -> None:
        target = self.dir / "acme-crm"
        target.mkdir()
        (target / "handler.py").write_text("x")
        plugin_store.remove_plugin_dir("acme-crm", self.dir)
        self.assertFalse(target.exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_plugin_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.plugin_store'`

- [ ] **Step 3: Implement the store**

Create `backend/app/services/plugin_store.py`:

```python
"""Filesystem + dependency handling for installed plugins."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import zipfile
from pathlib import Path

from app.models.plugin_schemas import PluginManifest

logger = logging.getLogger(__name__)

MAX_ZIP_BYTES = 20 * 1024 * 1024  # 20 MiB
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


class PluginInstallError(Exception):
    """Raised when a plugin zip is invalid or installation fails."""


def _safe_members(zf: zipfile.ZipFile, dest_root: Path) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    total = 0
    for info in zf.infolist():
        name = info.filename
        if name.endswith("/"):
            continue
        target = (dest_root / name).resolve()
        if not str(target).startswith(str(dest_root.resolve()) + "/"):
            raise PluginInstallError(f"Unsafe path in zip: {name}")
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise PluginInstallError("Plugin archive too large when uncompressed")
        members.append(info)
    return members


def extract_and_validate(zip_bytes: bytes, plugins_dir: Path) -> PluginManifest:
    """Validate a plugin zip, extract it to plugins_dir/<id>, install deps.

    Returns the parsed manifest. Raises PluginInstallError on any problem and
    removes a partially extracted directory.
    """
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise PluginInstallError("Plugin archive exceeds size limit")

    import io

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise PluginInstallError("Not a valid zip archive") from exc

    with zf:
        names = set(zf.namelist())
        if "plugin.json" not in names:
            raise PluginInstallError("plugin.json missing from archive")
        try:
            manifest = PluginManifest.model_validate(json.loads(zf.read("plugin.json")))
        except Exception as exc:
            raise PluginInstallError(f"Invalid plugin.json: {exc}") from exc
        if manifest.entry not in names:
            raise PluginInstallError(f"Entry file '{manifest.entry}' missing from archive")

        target = plugins_dir / manifest.id
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        try:
            members = _safe_members(zf, target)
            for info in members:
                out = target / info.filename
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(zf.read(info))
            if manifest.dependencies:
                _install_dependencies(manifest.dependencies)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

    return manifest


def _install_dependencies(dependencies: list[str]) -> None:
    """Install pip dependencies into the running instance (admin-gated)."""
    cmd = ["uv", "pip", "install", *dependencies]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PluginInstallError(f"Dependency install failed: {exc}") from exc
    if result.returncode != 0:
        raise PluginInstallError(f"Dependency install failed: {result.stderr.strip()}")


def remove_plugin_dir(plugin_id: str, plugins_dir: Path) -> None:
    shutil.rmtree(plugins_dir / plugin_id, ignore_errors=True)


def plugins_root() -> Path:
    from app.config import settings

    root = Path(settings.plugins_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_plugin_store.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/plugin_store.py backend/tests/test_plugin_store.py
git commit -m "feat(plugins): zip extraction, validation, dependency install store"
```

---

### Task 4: Plugin loader (manifest lookup + dynamic handler import)

**Files:**
- Create: `backend/app/services/plugin_loader.py`
- Test: `backend/tests/test_plugin_loader.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_plugin_loader.py`:

```python
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models.plugin_schemas import PluginManifest
from app.services import plugin_loader
from app.services.plugin_loader import PluginRuntimeError


def _write_plugin(root: Path, plugin_id: str, kind: str, body: str) -> None:
    pdir = root / plugin_id
    pdir.mkdir(parents=True)
    manifest = {"id": plugin_id, "name": plugin_id, "version": "1.0.0", "kind": kind, "fields": []}
    (pdir / "plugin.json").write_text(json.dumps(manifest))
    (pdir / "handler.py").write_text(body)


class PluginLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        plugin_loader.clear_cache()

    def test_load_manifest_from_disk(self) -> None:
        _write_plugin(self.root, "p1", "action", "def run(inputs, config, ctx):\n    return {}\n")
        manifest = plugin_loader.load_manifest("p1", self.root)
        self.assertIsInstance(manifest, PluginManifest)
        self.assertEqual(manifest.kind, "action")

    def test_run_action_handler(self) -> None:
        _write_plugin(self.root, "p1", "action", "def run(inputs, config, ctx):\n    return {'sum': inputs['a'] + config['b']}\n")
        result = plugin_loader.call_handler("p1", self.root, "run", {"inputs": {"a": 1}, "config": {"b": 2}, "ctx": {}})
        self.assertEqual(result, {"sum": 3})

    def test_run_trigger_handler(self) -> None:
        _write_plugin(self.root, "t1", "trigger", "def trigger(config, ctx):\n    return {'event': config['name']}\n")
        result = plugin_loader.call_handler("t1", self.root, "trigger", {"config": {"name": "ping"}, "ctx": {}})
        self.assertEqual(result, {"event": "ping"})

    def test_missing_function_raises(self) -> None:
        _write_plugin(self.root, "p1", "action", "x = 1\n")
        with self.assertRaises(PluginRuntimeError):
            plugin_loader.call_handler("p1", self.root, "run", {"inputs": {}, "config": {}, "ctx": {}})

    def test_missing_plugin_raises(self) -> None:
        with self.assertRaises(PluginRuntimeError):
            plugin_loader.load_manifest("nope", self.root)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_plugin_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.plugin_loader'`

- [ ] **Step 3: Implement the loader**

Create `backend/app/services/plugin_loader.py`:

```python
"""Load installed plugin manifests and dynamically import their handlers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from app.models.plugin_schemas import PluginManifest


class PluginRuntimeError(Exception):
    """Raised when a plugin cannot be loaded or executed."""


_MODULE_CACHE: dict[str, ModuleType] = {}


def clear_cache() -> None:
    _MODULE_CACHE.clear()


def load_manifest(plugin_id: str, plugins_dir: Path) -> PluginManifest:
    manifest_path = plugins_dir / plugin_id / "plugin.json"
    if not manifest_path.exists():
        raise PluginRuntimeError(f"Plugin '{plugin_id}' is not installed")
    try:
        return PluginManifest.model_validate(json.loads(manifest_path.read_text()))
    except Exception as exc:
        raise PluginRuntimeError(f"Invalid manifest for '{plugin_id}': {exc}") from exc


def _load_module(plugin_id: str, plugins_dir: Path) -> ModuleType:
    manifest = load_manifest(plugin_id, plugins_dir)
    handler_path = plugins_dir / plugin_id / manifest.entry
    cache_key = f"{plugin_id}:{manifest.version}"
    cached = _MODULE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if not handler_path.exists():
        raise PluginRuntimeError(f"Handler '{manifest.entry}' missing for '{plugin_id}'")
    spec = importlib.util.spec_from_file_location(f"heym_plugin_{plugin_id}", handler_path)
    if spec is None or spec.loader is None:
        raise PluginRuntimeError(f"Cannot load handler for '{plugin_id}'")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise PluginRuntimeError(f"Error importing '{plugin_id}': {exc}") from exc
    _MODULE_CACHE[cache_key] = module
    return module


def call_handler(plugin_id: str, plugins_dir: Path, function_name: str, kwargs: dict) -> object:
    module = _load_module(plugin_id, plugins_dir)
    fn = getattr(module, function_name, None)
    if not callable(fn):
        raise PluginRuntimeError(f"Plugin '{plugin_id}' has no '{function_name}' function")
    try:
        return fn(**kwargs)
    except Exception as exc:
        raise PluginRuntimeError(f"Plugin '{plugin_id}' {function_name} failed: {exc}") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_plugin_loader.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/plugin_loader.py backend/tests/test_plugin_loader.py
git commit -m "feat(plugins): dynamic handler loader + manifest lookup"
```

---

### Task 5: Plugins API router + gates + main.py registration

**Files:**
- Create: `backend/app/api/plugins.py`
- Modify: `backend/app/main.py:36` (import) and `:281` area (include_router)
- Test: `backend/tests/test_plugins_api.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_plugins_api.py`:

```python
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, status

from app.api import plugins
from app.config import settings


class PluginGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._enabled = settings.plugins_enabled
        self._admins = settings.plugin_admin_emails
        settings.plugins_enabled = True
        settings.plugin_admin_emails = "admin@example.com"

    def tearDown(self) -> None:
        settings.plugins_enabled = self._enabled
        settings.plugin_admin_emails = self._admins

    def test_require_enabled_raises_when_off(self) -> None:
        settings.plugins_enabled = False
        with self.assertRaises(HTTPException) as ctx:
            plugins.require_plugins_enabled()
        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)

    def test_require_admin_rejects_unlisted(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), email="viewer@example.com")
        with self.assertRaises(HTTPException) as ctx:
            plugins.require_plugin_admin(user)
        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)

    def test_require_admin_allows_listed(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), email="Admin@Example.com")
        plugins.require_plugin_admin(user)  # no raise

    async def test_uninstall_rejects_non_admin(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), email="viewer@example.com")
        with self.assertRaises(HTTPException) as ctx:
            await plugins.uninstall_plugin("acme-crm", current_user=user, db=AsyncMock())
        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_plugins_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.plugins'`

- [ ] **Step 3: Implement the router**

Create `backend/app/api/plugins.py`:

```python
"""Plugin management API (install/uninstall/list/toggle)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db.models import Plugin, User
from app.db.session import get_db
from app.models.plugin_schemas import PluginDoc, PluginManifest, PluginSummary
from app.services import plugin_loader, plugin_store
from app.services.plugin_store import PluginInstallError

router = APIRouter()


def require_plugins_enabled() -> None:
    if not settings.plugins_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plugins are disabled. Set HEYM_PLUGINS_ENABLED=true to enable them.",
        )


def _admin_emails() -> set[str]:
    return {e.strip().lower() for e in settings.plugin_admin_emails.split(",") if e.strip()}


def require_plugin_admin(current_user: User) -> None:
    require_plugins_enabled()
    allowed = _admin_emails()
    if not allowed or current_user.email.strip().lower() not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not allowed to manage plugins.",
        )


def _to_summary(plugin: Plugin) -> PluginSummary:
    manifest = PluginManifest.model_validate(plugin.manifest)
    return PluginSummary(
        id=plugin.plugin_id,
        name=plugin.name,
        version=plugin.version,
        kind=plugin.kind,  # type: ignore[arg-type]
        description=plugin.description,
        enabled=plugin.enabled,
        fields=manifest.fields,
        dsl_hint=manifest.dsl_hint,
        doc_slug=manifest.resolved_doc_slug(),
        has_icon=(plugin_store.plugins_root() / plugin.plugin_id / "icon.svg").exists(),
    )


@router.get("", response_model=list[PluginSummary])
async def list_plugins(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PluginSummary]:
    require_plugins_enabled()
    rows = (await db.execute(select(Plugin))).scalars().all()
    return [_to_summary(p) for p in rows]


@router.get("/{plugin_id}/doc", response_model=PluginDoc)
async def get_plugin_doc(
    plugin_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PluginDoc:
    require_plugins_enabled()
    plugin = (
        await db.execute(select(Plugin).where(Plugin.plugin_id == plugin_id))
    ).scalar_one_or_none()
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    readme = plugin_store.plugins_root() / plugin_id / "README.md"
    markdown = readme.read_text() if readme.exists() else ""
    manifest = PluginManifest.model_validate(plugin.manifest)
    return PluginDoc(id=plugin_id, name=plugin.name, doc_slug=manifest.resolved_doc_slug(), markdown=markdown)


@router.post("/install", response_model=PluginSummary)
async def install_plugin(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PluginSummary:
    require_plugin_admin(current_user)
    data = await file.read()
    try:
        manifest = plugin_store.extract_and_validate(data, plugin_store.plugins_root())
    except PluginInstallError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    plugin_loader.clear_cache()
    existing = (
        await db.execute(select(Plugin).where(Plugin.plugin_id == manifest.id))
    ).scalar_one_or_none()
    if existing is None:
        existing = Plugin(plugin_id=manifest.id)
        db.add(existing)
    existing.name = manifest.name
    existing.version = manifest.version
    existing.kind = manifest.kind
    existing.description = manifest.description
    existing.manifest = manifest.model_dump(by_alias=True)
    existing.enabled = True
    existing.installed_by = current_user.email
    await db.commit()
    await db.refresh(existing)
    return _to_summary(existing)


@router.patch("/{plugin_id}", response_model=PluginSummary)
async def set_plugin_enabled(
    plugin_id: str,
    enabled: bool,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PluginSummary:
    require_plugin_admin(current_user)
    plugin = (
        await db.execute(select(Plugin).where(Plugin.plugin_id == plugin_id))
    ).scalar_one_or_none()
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    plugin.enabled = enabled
    await db.commit()
    await db.refresh(plugin)
    return _to_summary(plugin)


@router.delete("/{plugin_id}")
async def uninstall_plugin(
    plugin_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    require_plugin_admin(current_user)
    plugin = (
        await db.execute(select(Plugin).where(Plugin.plugin_id == plugin_id))
    ).scalar_one_or_none()
    if plugin is not None:
        await db.delete(plugin)
        await db.commit()
    plugin_store.remove_plugin_dir(plugin_id, plugin_store.plugins_root())
    plugin_loader.clear_cache()
    return {"status": "uninstalled", "plugin_id": plugin_id}
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py:36`, add `plugins,` to the api import block (alongside `logs,`). After line 281 (`app.include_router(logs.router, ...)`):

```python
app.include_router(plugins.router, prefix="/api/plugins", tags=["Plugins"])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_plugins_api.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/plugins.py backend/app/main.py backend/tests/test_plugins_api.py
git commit -m "feat(plugins): management API (install/uninstall/list/toggle)"
```

---

## Phase 2 — Execution

### Task 6: Plugin node + trigger node handlers + registry

**Files:**
- Create: `backend/app/services/node_execution/nodes/plugin_node.py`
- Create: `backend/app/services/node_execution/nodes/plugin_trigger_node.py`
- Modify: `backend/app/services/node_execution/registry.py:11` (add two entries)
- Test: `backend/tests/test_plugin_node.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_plugin_node.py`:

```python
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from app.services import plugin_loader
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import plugin_node, plugin_trigger_node


def _write_plugin(root: Path, plugin_id: str, kind: str, body: str) -> None:
    pdir = root / plugin_id
    pdir.mkdir(parents=True)
    (pdir / "plugin.json").write_text(
        json.dumps({"id": plugin_id, "name": plugin_id, "version": "1.0.0", "kind": kind, "fields": []})
    )
    (pdir / "handler.py").write_text(body)


def _ctx(node_data: dict, inputs: dict) -> NodeExecutionContext:
    executor = SimpleNamespace(
        resolve_expression=lambda value, *_a, **_k: value,
        _first_visible_input=lambda i: next(iter(i.values()), None),
    )
    return NodeExecutionContext(
        executor=executor,
        node_id="n1",
        inputs=inputs,
        allow_branch_skip=False,
        start_time=0.0,
        node={"id": "n1"},
        node_type=node_data.get("_type", "plugin"),
        node_data=node_data,
        node_label="plugin1",
    )


class PluginNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        plugin_loader.clear_cache()

    def test_action_node_runs_handler(self) -> None:
        _write_plugin(self.root, "acme", "action", "def run(inputs, config, ctx):\n    return {'result': config['x']}\n")
        ctx = _ctx({"pluginId": "acme", "config": {"x": "hi"}}, {"in": {"v": 1}})
        with patch.object(plugin_node.plugin_store, "plugins_root", return_value=self.root):
            output = plugin_node.execute(ctx)
        self.assertEqual(output, {"result": "hi"})

    def test_trigger_node_runs_handler(self) -> None:
        _write_plugin(self.root, "tick", "trigger", "def trigger(config, ctx):\n    return {'fired': config['name']}\n")
        ctx = _ctx({"pluginId": "tick", "config": {"name": "ping"}}, {})
        with patch.object(plugin_trigger_node.plugin_store, "plugins_root", return_value=self.root):
            output = plugin_trigger_node.execute(ctx)
        self.assertEqual(output, {"fired": "ping"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_plugin_node.py -v`
Expected: FAIL with `ImportError` (no `plugin_node` module)

- [ ] **Step 3: Implement the action handler**

Create `backend/app/services/node_execution/nodes/plugin_node.py`:

```python
from __future__ import annotations

from app.services import plugin_loader, plugin_store
from app.services.node_execution.base import NodeExecutionContext


def _resolve_config(ctx: NodeExecutionContext) -> dict:
    raw_config = ctx.node_data.get("config", {}) or {}
    resolved: dict = {}
    for key, value in raw_config.items():
        if isinstance(value, str) and value.startswith("$"):
            resolved[key] = ctx.executor.resolve_expression(
                value, ctx.inputs, ctx.node_id, preserve_type=True
            )
        else:
            resolved[key] = value
    return resolved


def _safe_ctx(ctx: NodeExecutionContext) -> dict:
    return {"node_id": ctx.node_id, "node_label": ctx.node_label}


def execute(ctx: NodeExecutionContext) -> object:
    """Execute a `plugin` (action) node by calling its handler's run()."""
    plugin_id = ctx.node_data.get("pluginId")
    if not plugin_id:
        raise ValueError("Plugin node is missing pluginId")
    config = _resolve_config(ctx)
    result = plugin_loader.call_handler(
        plugin_id,
        plugin_store.plugins_root(),
        "run",
        {"inputs": ctx.inputs, "config": config, "ctx": _safe_ctx(ctx)},
    )
    return result if isinstance(result, dict) else {"value": result}
```

- [ ] **Step 4: Implement the trigger handler**

Create `backend/app/services/node_execution/nodes/plugin_trigger_node.py`:

```python
from __future__ import annotations

from app.services import plugin_loader, plugin_store
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes.plugin_node import _resolve_config, _safe_ctx


def execute(ctx: NodeExecutionContext) -> object:
    """Execute a `pluginTrigger` node by calling its handler's trigger()."""
    plugin_id = ctx.node_data.get("pluginId")
    if not plugin_id:
        raise ValueError("Plugin trigger node is missing pluginId")
    config = _resolve_config(ctx)
    result = plugin_loader.call_handler(
        plugin_id,
        plugin_store.plugins_root(),
        "trigger",
        {"config": config, "ctx": _safe_ctx(ctx)},
    )
    return result if isinstance(result, dict) else {"value": result}
```

- [ ] **Step 5: Register the handlers**

In `backend/app/services/node_execution/registry.py`, add to `_HANDLER_MODULES` (keep alphabetical-ish placement near other `p` entries):

```python
    "plugin": "plugin_node",
    "pluginTrigger": "plugin_trigger_node",
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_plugin_node.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/node_execution/nodes/plugin_node.py backend/app/services/node_execution/nodes/plugin_trigger_node.py backend/app/services/node_execution/registry.py backend/tests/test_plugin_node.py
git commit -m "feat(plugins): plugin + pluginTrigger node handlers"
```

---

## Phase 3 — DSL Prompt Injection

### Task 7: Inject installed plugins into `build_assistant_prompt`

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py` (`build_assistant_prompt` signature + body, near line 4465-4524)
- Modify: `backend/app/api/ai_assistant.py` (pass installed plugins) and `backend/app/api/dashboards.py` callers
- Test: `backend/tests/test_plugin_dsl_prompt.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_plugin_dsl_prompt.py`:

```python
import unittest

from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT, build_assistant_prompt


class PluginDslPromptTests(unittest.TestCase):
    def test_injects_installed_plugins_section(self) -> None:
        plugins = [
            {
                "id": "acme-crm",
                "kind": "action",
                "description": "Create Acme records",
                "dsl_hint": "Use to create a CRM record",
                "fields": [{"key": "apiKey", "label": "API Key", "type": "string"}],
            }
        ]
        prompt = build_assistant_prompt(None, None, None, installed_plugins=plugins)
        self.assertIn("Installed Plugins", prompt)
        self.assertIn("acme-crm", prompt)
        self.assertIn("Use to create a CRM record", prompt)

    def test_no_section_without_plugins(self) -> None:
        prompt = build_assistant_prompt(None, None, None)
        self.assertNotIn("Installed Plugins", prompt)

    def test_static_prompt_constant_unchanged(self) -> None:
        # Guard: plugin injection must NOT leak into the synced static constant.
        self.assertNotIn("Installed Plugins", WORKFLOW_DSL_SYSTEM_PROMPT)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_plugin_dsl_prompt.py -v`
Expected: FAIL — `build_assistant_prompt() got an unexpected keyword argument 'installed_plugins'`

- [ ] **Step 3: Add the parameter + section**

In `backend/app/services/workflow_dsl_prompt.py`, update the signature (line ~4465):

```python
def build_assistant_prompt(
    current_workflow: dict | None = None,
    available_workflows: list[dict] | None = None,
    user_rules: str | None = None,
    available_node_templates: list[dict] | None = None,
    installed_plugins: list[dict] | None = None,
) -> str:
```

At the end of the function, just before the final `return prompt`, add:

```python
    if installed_plugins:
        prompt += "\n\n## Installed Plugins\n\n"
        prompt += (
            "These plugins are installed on this instance and behave like custom nodes. "
            "Use node type `plugin` for actions and `pluginTrigger` for triggers, and set "
            "`pluginId` to the plugin's id. Put field values under `config`.\n\n"
        )
        for plugin in installed_plugins:
            prompt += f"- **{plugin.get('id', '')}** ({plugin.get('kind', 'action')}): "
            prompt += f"{plugin.get('description', '')}\n"
            hint = plugin.get("dsl_hint")
            if hint:
                prompt += f"  Usage: {hint}\n"
            fields = plugin.get("fields", [])
            if fields:
                prompt += "  config fields:\n"
                for field in fields:
                    prompt += f"    - `{field.get('key')}` ({field.get('type', 'string')})\n"
```

- [ ] **Step 4: Wire callers to pass installed plugins**

Add a helper in `backend/app/api/ai_assistant.py` (near the other `_format_*` helpers) and pass it at the two `build_assistant_prompt(...)` call sites (lines ~1122, ~1244):

```python
async def _load_installed_plugins(db: AsyncSession) -> list[dict]:
    from sqlalchemy import select

    from app.config import settings
    from app.db.models import Plugin
    from app.models.plugin_schemas import PluginManifest

    if not settings.plugins_enabled:
        return []
    rows = (await db.execute(select(Plugin).where(Plugin.enabled.is_(True)))).scalars().all()
    result: list[dict] = []
    for p in rows:
        manifest = PluginManifest.model_validate(p.manifest)
        result.append(
            {
                "id": p.plugin_id,
                "kind": p.kind,
                "description": p.description,
                "dsl_hint": manifest.dsl_hint,
                "fields": [f.model_dump() for f in manifest.fields],
            }
        )
    return result
```

At each call site change `build_assistant_prompt(...)` to also pass `installed_plugins=await _load_installed_plugins(db)`. (The handlers already receive a `db: AsyncSession`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_plugin_dsl_prompt.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the existing DSL sync guard to confirm no drift**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "dsl or assistant_prompt" -q`
Expected: PASS (no sync-diff failures)

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/workflow_dsl_prompt.py backend/app/api/ai_assistant.py backend/tests/test_plugin_dsl_prompt.py
git commit -m "feat(plugins): inject installed plugins into assistant prompt"
```

---

## Phase 4 — Frontend

### Task 8: Frontend types + plugins API client

**Files:**
- Modify: `frontend/src/types/workflow.ts:130` (`NodeType` union) + plugin node data interface
- Create: `frontend/src/services/plugins.ts`

- [ ] **Step 1: Add node types**

In `frontend/src/types/workflow.ts`, add to the `NodeType` union (next to other action/trigger types):

```typescript
  | "plugin"
  | "pluginTrigger"
```

Add an exported interface for plugin metadata (place near other shared types):

```typescript
export interface PluginFieldDef {
  key: string;
  label: string;
  type: "string" | "number" | "boolean" | "select";
  required?: boolean;
  secret?: boolean;
  default?: string | number | boolean | null;
  options?: { label: string; value: string }[];
  dynamic?: boolean;
  expression?: boolean;
}

export interface PluginSummary {
  id: string;
  name: string;
  version: string;
  kind: "action" | "trigger";
  description: string;
  enabled: boolean;
  fields: PluginFieldDef[];
  dsl_hint?: string;
  doc_slug?: string;
  has_icon?: boolean;
}
```

- [ ] **Step 2: Create the API client**

Create `frontend/src/services/plugins.ts` (follow the axios client pattern used by sibling files in `frontend/src/services/`):

```typescript
import { api } from "./api";

import type { PluginSummary } from "@/types/workflow";

export interface PluginDoc {
  id: string;
  name: string;
  doc_slug: string;
  markdown: string;
}

export async function listPlugins(): Promise<PluginSummary[]> {
  const { data } = await api.get<PluginSummary[]>("/api/plugins");
  return data;
}

export async function getPluginDoc(pluginId: string): Promise<PluginDoc> {
  const { data } = await api.get<PluginDoc>(`/api/plugins/${pluginId}/doc`);
  return data;
}

export async function installPlugin(file: File): Promise<PluginSummary> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<PluginSummary>("/api/plugins/install", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function setPluginEnabled(pluginId: string, enabled: boolean): Promise<PluginSummary> {
  const { data } = await api.patch<PluginSummary>(`/api/plugins/${pluginId}?enabled=${enabled}`);
  return data;
}

export async function uninstallPlugin(pluginId: string): Promise<void> {
  await api.delete(`/api/plugins/${pluginId}`);
}
```

Note: confirm the axios instance export name in `frontend/src/services/api.ts` (it may be a default export); match it.

- [ ] **Step 3: Verify typecheck**

Run: `cd frontend && bun run typecheck`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/services/plugins.ts
git commit -m "feat(plugins): frontend types + api client"
```

---

### Task 9: Node palette integration

**Files:**
- Modify: `frontend/src/components/Panels/NodePanel.vue`

- [ ] **Step 1: Load and render installed plugins**

In `NodePanel.vue` `<script setup>`, fetch plugins on mount (guarded so a 404 when plugins are disabled is swallowed):

```typescript
import { listPlugins } from "@/services/plugins";
import type { PluginSummary } from "@/types/workflow";

const plugins = ref<PluginSummary[]>([]);

onMounted(async () => {
  try {
    plugins.value = (await listPlugins()).filter((p) => p.enabled);
  } catch {
    plugins.value = [];
  }
});
```

Add a "Plugins" palette section (mirror an existing node group's template). Each plugin card, when dragged/dropped, must create a node with:

```typescript
function pluginNodePayload(plugin: PluginSummary): { type: string; data: Record<string, unknown> } {
  return {
    type: plugin.kind === "trigger" ? "pluginTrigger" : "plugin",
    data: { pluginId: plugin.id, label: plugin.name, config: {} },
  };
}
```

Render the section only when `plugins.value.length > 0` (so when the feature is off, nothing shows). Use the plugin icon endpoint `/api/plugins/{id}/icon` if `has_icon`, else a default puzzle-piece icon already available in the icon set.

- [ ] **Step 2: Verify lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Panels/NodePanel.vue
git commit -m "feat(plugins): show installed plugins in node palette"
```

Note: if `has_icon` icon serving is desired, add a `GET /api/plugins/{plugin_id}/icon` FileResponse endpoint to `backend/app/api/plugins.py` (gated by `require_plugins_enabled`) returning the `icon.svg`; otherwise skip icons and always use the default. Keep this optional to avoid scope creep.

---

### Task 10: `PluginNodeProperties.vue` schema-driven config form

**Files:**
- Create: `frontend/src/components/Panels/propertiesPanel/nodes/PluginNodeProperties.vue`
- Modify: `frontend/src/components/Panels/PropertiesPanel.vue` (route `plugin`/`pluginTrigger` to the new component)

- [ ] **Step 1: Create the component**

Create `frontend/src/components/Panels/propertiesPanel/nodes/PluginNodeProperties.vue` following the existing node-properties component pattern (e.g. `SetJsonOutputMapperNodeProperties.vue`). It must:
- accept the selected node as a prop,
- look up the plugin manifest from a `listPlugins()` cache (by `node.data.pluginId`),
- render one input per `field` (string→text/secret, number→number, boolean→switch, select→dropdown),
- write values into `node.data.config[field.key]`,
- mark `field.expression`/`field.dynamic` fields as expression-eligible using the same expression affordance other node forms use.

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import type { PluginFieldDef, PluginSummary } from "@/types/workflow";
import { listPlugins } from "@/services/plugins";

const props = defineProps<{ nodeData: Record<string, unknown> }>();

const plugins = ref<PluginSummary[]>([]);
onMounted(async () => {
  try {
    plugins.value = await listPlugins();
  } catch {
    plugins.value = [];
  }
});

const manifest = computed<PluginSummary | undefined>(() =>
  plugins.value.find((p) => p.id === props.nodeData.pluginId),
);

const fields = computed<PluginFieldDef[]>(() => manifest.value?.fields ?? []);

function config(): Record<string, unknown> {
  if (typeof props.nodeData.config !== "object" || props.nodeData.config === null) {
    props.nodeData.config = {};
  }
  return props.nodeData.config as Record<string, unknown>;
}

function setValue(key: string, value: unknown): void {
  config()[key] = value;
}
</script>

<template>
  <div class="space-y-3">
    <p v-if="!manifest" class="text-sm text-muted-foreground">Plugin not found or disabled.</p>
    <div v-for="field in fields" :key="field.key" class="space-y-1">
      <label class="text-sm font-medium">{{ field.label }}</label>
      <input
        v-if="field.type === 'string' || field.type === 'number'"
        :type="field.secret ? 'password' : field.type === 'number' ? 'number' : 'text'"
        class="w-full rounded border px-2 py-1 text-sm"
        :value="(config()[field.key] as string | number | undefined) ?? ''"
        @input="setValue(field.key, ($event.target as HTMLInputElement).value)"
      />
      <input
        v-else-if="field.type === 'boolean'"
        type="checkbox"
        :checked="Boolean(config()[field.key])"
        @change="setValue(field.key, ($event.target as HTMLInputElement).checked)"
      />
      <select
        v-else-if="field.type === 'select'"
        class="w-full rounded border px-2 py-1 text-sm"
        :value="(config()[field.key] as string | undefined) ?? ''"
        @change="setValue(field.key, ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="opt in field.options ?? []" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </option>
      </select>
    </div>
  </div>
</template>
```

Note: match the actual prop/emit conventions of the sibling node-properties components (they likely receive the node and emit updates via the panel's shared composable rather than mutating a prop). Align with that pattern instead of mutating `props.nodeData` directly if the codebase forbids prop mutation under strict lint.

- [ ] **Step 2: Route plugin node types in PropertiesPanel.vue**

In `PropertiesPanel.vue`, add (mirroring how other node types are routed to their components):

```vue
<PluginNodeProperties
  v-else-if="selectedNode.type === 'plugin' || selectedNode.type === 'pluginTrigger'"
  :node-data="selectedNode.data"
/>
```

and import it. Do not add field logic inline (AGENTS.md PropertiesPanel modularity rule).

- [ ] **Step 3: Verify lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Panels/propertiesPanel/nodes/PluginNodeProperties.vue frontend/src/components/Panels/PropertiesPanel.vue
git commit -m "feat(plugins): schema-driven plugin node config form"
```

---

### Task 11: Settings → Plugins tab

**Files:**
- Modify: `frontend/src/components/Layout/UserSettingsDialog.vue`

- [ ] **Step 1: Add the tab**

In `UserSettingsDialog.vue`:
- Extend `SettingsTab` (line 22): `... | "observability" | "plugins";`
- Add a tab button next to "Observability" (lines ~264-267 pattern), shown only when plugins are enabled. Determine enabled state by attempting `listPlugins()` (success → feature on; 404 → hide tab).
- Add the tab panel: a list of plugins with an enable/disable toggle (`setPluginEnabled`), and — only for admins — a file `<input type="file" accept=".zip">` calling `installPlugin`, plus an uninstall button calling `uninstallPlugin`.
- Admin visibility: the backend already enforces; for the UI, attempt the admin action and surface a 403 toast, OR expose admin status. Simplest: show upload/uninstall controls to everyone but rely on backend 403 with a friendly message. (Avoid duplicating the email allowlist on the client.)

```typescript
import { listPlugins, installPlugin, uninstallPlugin, setPluginEnabled } from "@/services/plugins";
import type { PluginSummary } from "@/types/workflow";

const pluginsEnabled = ref(false);
const installedPlugins = ref<PluginSummary[]>([]);
const pluginError = ref<string | null>(null);

async function loadPlugins(): Promise<void> {
  try {
    installedPlugins.value = await listPlugins();
    pluginsEnabled.value = true;
  } catch {
    pluginsEnabled.value = false;
  }
}

async function onInstallFile(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  pluginError.value = null;
  try {
    await installPlugin(file);
    await loadPlugins();
  } catch (err) {
    pluginError.value = err instanceof Error ? err.message : "Install failed";
  }
}
```

Wire `loadPlugins()` into the existing `watch(activeTab, ...)` (line ~147) so it loads when the plugins tab opens, mirroring the observability pattern.

- [ ] **Step 2: Verify lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Layout/UserSettingsDialog.vue
git commit -m "feat(plugins): Settings Plugins tab (install/uninstall/toggle)"
```

---

### Task 12: `/documentation` dynamic Plugins category

**Files:**
- Modify: `frontend/src/views/DocsView.vue` (+ wherever `DOCS_MANIFEST` is consumed for the sidebar)

- [ ] **Step 1: Append a runtime Plugins category**

In `DocsView.vue`, after loading the static `DOCS_MANIFEST`, fetch installed plugins and add a dynamic category:

```typescript
import { listPlugins, getPluginDoc } from "@/services/plugins";

const pluginCategory = ref<{ id: string; label: string; items: { slug: string; title: string }[] } | null>(null);

onMounted(async () => {
  try {
    const plugins = (await listPlugins()).filter((p) => p.enabled);
    if (plugins.length > 0) {
      pluginCategory.value = {
        id: "plugins",
        label: "Plugins",
        items: plugins.map((p) => ({ slug: `plugin:${p.id}`, title: p.name })),
      };
    }
  } catch {
    pluginCategory.value = null;
  }
});
```

When a `plugin:<id>` slug is selected, render markdown from `getPluginDoc(id)` instead of the static markdown loader. Merge `pluginCategory.value` into the sidebar category list used by the template (without mutating the imported `DOCS_MANIFEST` constant).

- [ ] **Step 2: Verify lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/DocsView.vue
git commit -m "feat(plugins): list plugin docs under /documentation"
```

---

## Phase 5 — Ops, Docs, Verification

### Task 13: Env var examples + ops files

**Files:**
- Modify: `.env.example`, `docker-compose.yml`, `run.sh`, `deploy.sh`

- [ ] **Step 1: Add env examples**

In `.env.example` after the `DOCKER_LOGS_*` lines:

```
# Plugins (custom nodes installed as zip). Disabled by default.
HEYM_PLUGINS_ENABLED=false
HEYM_PLUGIN_ADMIN_EMAILS=
HEYM_PLUGINS_DIR=data/plugins
```

In `docker-compose.yml`, under the backend `environment:` block (next to `DOCKER_LOGS_ALLOWED_EMAILS`):

```yaml
      HEYM_PLUGINS_ENABLED: ${HEYM_PLUGINS_ENABLED:-false}
      HEYM_PLUGIN_ADMIN_EMAILS: ${HEYM_PLUGIN_ADMIN_EMAILS:-}
      HEYM_PLUGINS_DIR: ${HEYM_PLUGINS_DIR:-/app/data/plugins}
```

Add a volume mount for plugin persistence (so installs survive restarts):

```yaml
      - ./data/plugins:/app/data/plugins
```

- [ ] **Step 2: Commit**

```bash
git add .env.example docker-compose.yml run.sh deploy.sh
git commit -m "chore(plugins): document HEYM_PLUGINS_* env vars + volume"
```

---

### Task 14: Node reference docs (heym-documentation skill)

**Files:**
- Create: `frontend/src/docs/content/nodes/plugin-node.md`, `frontend/src/docs/content/nodes/plugin-trigger-node.md`
- Modify: `frontend/src/docs/manifest.ts`, `frontend/src/docs/content/reference/features.md`, `frontend/src/docs/content/reference/node-types.md`

- [ ] **Step 1: Invoke the heym-documentation skill**

Use the `heym-documentation` skill to add the two node pages and register them, plus the plugins concept page (installation, manifest format, security/trust model). Follow the node-integration policy in `AGENTS.md`.

- [ ] **Step 2: Verify typecheck (manifest.ts) + build**

Run: `cd frontend && bun run typecheck && bun run build`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/docs/
git commit -m "docs(plugins): node reference + plugins concept page"
```

---

### Task 15: Full verification

- [ ] **Step 1: Backend checks**

Run: `SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh`
Expected: ruff format clean, lint clean, all backend tests pass (including the six new test files).

- [ ] **Step 2: Manual smoke (with plugins enabled)**

```bash
HEYM_PLUGINS_ENABLED=true HEYM_PLUGIN_ADMIN_EMAILS=you@example.com ./run.sh
```
Verify: Settings → Plugins tab appears for the admin email; install a sample zip; the plugin appears in the node palette; dropping it onto the canvas creates a `plugin`/`pluginTrigger` node; its config form renders manifest fields; running a workflow executes the handler; the plugin doc shows under `/documentation`; the AI assistant ("create a workflow that uses the Acme plugin") emits a `plugin` node.

- [ ] **Step 3: Commit any formatting-only diffs**

```bash
git add -A && git commit -m "chore(plugins): formatting" || echo "nothing to format"
```

---

## Self-Review Notes (spec coverage)

- plugins enabled flag → Task 1 (`HEYM_PLUGINS_ENABLED`), Task 5 gate, Task 13 ops.
- zip install/uninstall → Task 3 (store) + Task 5 (API).
- plugin = custom node (action + trigger) → Task 6 handlers + registry.
- admin = docker-logs-style email allowlist → Task 5 (`HEYM_PLUGIN_ADMIN_EMAILS`, `require_plugin_admin`).
- Settings dialog Plugins tab → Task 11.
- docs under /documentation → Task 12 + Task 14.
- DSL prompt injection (assistant + chat canvas) → Task 7 (with static-constant guard).
- dependencies install → Task 3 `_install_dependencies`.
- trusted in-process execution → Task 4 loader + Task 6 handlers.
