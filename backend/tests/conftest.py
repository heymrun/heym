"""Test-run defaults that must not come from the developer's own .env.

`Settings` reads .env at import, so a machine that runs Heym with a cluster
enabled ran different code than CI: API, trigger and cron runs were enqueued
onto the run queue instead of executed in-process, and a dozen suites failed
here and nowhere else. Pinning the cluster off makes a local run mean what a
CI run means; the suites that are about the cluster turn it back on themselves.
"""

from unittest.mock import patch

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def cluster_disabled_unless_a_test_asks_for_it():
    with patch.object(settings, "cluster_enabled", False):
        yield


@pytest.fixture(autouse=True)
def instance_admins_empty_unless_a_test_configures_them():
    """Never grant permissions or change query paths from a developer's .env."""
    with patch.object(settings, "admin_emails", ""):
        yield


@pytest.fixture(autouse=True)
def docker_sandbox_backend_unless_a_test_selects_one():
    """Pin the sandbox backend to Docker and build the manager before the test body.

    Built lazily inside a test, the manager would probe Docker through whatever
    subprocess function that test patches. Tests about backend selection reset the
    manager themselves.
    """
    from app.services.sandbox import get_sandbox_manager, reset_sandbox_manager

    with patch.dict("os.environ", {"HEYM_SANDBOX_BACKEND": "docker"}):
        reset_sandbox_manager()
        get_sandbox_manager()
        yield
    reset_sandbox_manager()
