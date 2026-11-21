"""Cookies a workflow run receives stay with that run.

The guarded HTTP client is shared by every run in the process, and httpx keeps each
Set-Cookie on the client that received it. A session cookie from one user's run was
therefore sent with the next request any run made to the same site. The shared client
now stores no cookie; each run keeps its own jar, which the client's hooks use while a
request of that run is in flight.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from http.cookiejar import CookieJar, DefaultCookiePolicy

import httpx

_RUN_COOKIES: ContextVar[httpx.Cookies | None] = ContextVar("heym_run_cookies", default=None)


def refusing_cookie_jar() -> CookieJar:
    """Return a jar that stores no cookie, for a client that every run shares."""
    return CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))


@contextmanager
def run_cookies(jar: httpx.Cookies) -> Iterator[None]:
    """Send and keep the cookies of ``jar`` for the requests made inside this block."""
    token = _RUN_COOKIES.set(jar)
    try:
        yield
    finally:
        _RUN_COOKIES.reset(token)


def add_run_cookies(request: httpx.Request) -> None:
    """Request hook: send the run's cookies, unless the request sets its own Cookie header."""
    jar = _RUN_COOKIES.get()
    if jar is not None:
        jar.set_cookie_header(request)


def keep_run_cookies(response: httpx.Response) -> None:
    """Response hook: keep the cookies a response sets in the run's jar."""
    jar = _RUN_COOKIES.get()
    if jar is not None:
        jar.extract_cookies(response)
