import hashlib
import uuid
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import HTTPException

from app.api.avatars import get_user_avatar
from app.services import gravatar
from app.services.gravatar import GravatarImage, get_gravatar, gravatar_hash

_PNG = b"\x89PNG\r\n\x1a\nfake"


def _client_returning(response: httpx.Response | Exception) -> MagicMock:
    client = MagicMock()
    if isinstance(response, Exception):
        client.get = AsyncMock(side_effect=response)
    else:
        client.get = AsyncMock(return_value=response)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=context)
    factory.client = client
    return factory


def _request(etag: str | None = None) -> MagicMock:
    request = MagicMock()
    request.headers = {"if-none-match": etag} if etag else {}
    return request


class GravatarHashTest(TestCase):
    def test_hash_is_sha256_of_trimmed_lowercase_email(self) -> None:
        expected = hashlib.sha256(b"ada@example.com").hexdigest()
        self.assertEqual(gravatar_hash("  Ada@Example.COM "), expected)


class GetGravatarTest(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        gravatar.clear_gravatar_cache()

    def tearDown(self) -> None:
        gravatar.clear_gravatar_cache()

    async def test_returns_image_and_asks_gravatar_for_404_when_missing(self) -> None:
        factory = _client_returning(
            httpx.Response(200, content=_PNG, headers={"content-type": "image/png"})
        )
        with patch("app.services.gravatar.httpx.AsyncClient", factory):
            image = await get_gravatar("ada@example.com")

        self.assertIsNotNone(image)
        assert image is not None
        self.assertEqual(image.content, _PNG)
        self.assertEqual(image.content_type, "image/png")
        self.assertTrue(image.etag.startswith('"') and image.etag.endswith('"'))
        url = factory.client.get.await_args.args[0]
        self.assertTrue(url.endswith(gravatar_hash("ada@example.com")))
        self.assertEqual(factory.client.get.await_args.kwargs["params"]["d"], "404")
        self.assertIn("Heym", factory.call_args.kwargs["headers"]["User-Agent"])

    async def test_hit_is_served_from_cache(self) -> None:
        factory = _client_returning(
            httpx.Response(200, content=_PNG, headers={"content-type": "image/png"})
        )
        with patch("app.services.gravatar.httpx.AsyncClient", factory):
            first = await get_gravatar("ada@example.com")
            second = await get_gravatar("ADA@example.com")

        self.assertEqual(first, second)
        self.assertEqual(factory.client.get.await_count, 1)

    async def test_miss_is_cached_so_gravatar_is_not_asked_again(self) -> None:
        factory = _client_returning(httpx.Response(404, text="Not Found"))
        with patch("app.services.gravatar.httpx.AsyncClient", factory):
            self.assertIsNone(await get_gravatar("nobody@example.com"))
            self.assertIsNone(await get_gravatar("nobody@example.com"))

        self.assertEqual(factory.client.get.await_count, 1)

    async def test_network_failure_returns_none_and_is_cached(self) -> None:
        factory = _client_returning(httpx.ConnectError("offline"))
        with patch("app.services.gravatar.httpx.AsyncClient", factory):
            self.assertIsNone(await get_gravatar("ada@example.com"))
            self.assertIsNone(await get_gravatar("ada@example.com"))

        self.assertEqual(factory.client.get.await_count, 1)

    async def test_expired_entry_is_fetched_again(self) -> None:
        factory = _client_returning(httpx.Response(404, text="Not Found"))
        with (
            patch("app.services.gravatar.httpx.AsyncClient", factory),
            patch("app.services.gravatar.time.monotonic", side_effect=[0.0, 10**9, 10**9]),
        ):
            await get_gravatar("ada@example.com")
            await get_gravatar("ada@example.com")

        self.assertEqual(factory.client.get.await_count, 2)

    async def test_rejects_non_raster_content(self) -> None:
        # An SVG served from our own origin could run script when opened directly.
        for content_type in ("image/svg+xml", "text/html; charset=utf-8"):
            gravatar.clear_gravatar_cache()
            factory = _client_returning(
                httpx.Response(200, content=b"<svg/>", headers={"content-type": content_type})
            )
            with patch("app.services.gravatar.httpx.AsyncClient", factory):
                self.assertIsNone(await get_gravatar("ada@example.com"), content_type)

    async def test_rejects_oversized_image(self) -> None:
        big = b"x" * (gravatar.MAX_IMAGE_BYTES + 1)
        factory = _client_returning(
            httpx.Response(200, content=big, headers={"content-type": "image/jpeg"})
        )
        with patch("app.services.gravatar.httpx.AsyncClient", factory):
            self.assertIsNone(await get_gravatar("ada@example.com"))

    async def test_cache_is_bounded(self) -> None:
        factory = _client_returning(httpx.Response(404, text="Not Found"))
        with (
            patch("app.services.gravatar.httpx.AsyncClient", factory),
            patch.object(gravatar, "MAX_CACHE_ENTRIES", 3),
        ):
            for index in range(5):
                await get_gravatar(f"user{index}@example.com")

        self.assertEqual(len(gravatar._cache), 3)


class AvatarEndpointTest(IsolatedAsyncioTestCase):
    def _db_returning_email(self, email: str | None) -> AsyncMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = email
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)
        return db

    def _user(self) -> MagicMock:
        user = MagicMock()
        user.id = uuid.uuid4()
        user.email = "me@example.com"
        return user

    async def test_own_avatar_uses_current_user_email_without_a_query(self) -> None:
        user = self._user()
        db = self._db_returning_email(None)
        image = GravatarImage(content=_PNG, content_type="image/png", etag='"abc"')
        with patch("app.api.avatars.get_gravatar", AsyncMock(return_value=image)) as fetch:
            response = await get_user_avatar(user.id, _request(), current_user=user, db=db)

        fetch.assert_awaited_once_with("me@example.com")
        db.execute.assert_not_awaited()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, _PNG)
        self.assertEqual(response.media_type, "image/png")
        self.assertEqual(response.headers["etag"], '"abc"')
        self.assertIn("private", response.headers["cache-control"])
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    async def test_other_user_avatar_looks_up_their_email(self) -> None:
        db = self._db_returning_email("teammate@example.com")
        image = GravatarImage(content=_PNG, content_type="image/png", etag='"abc"')
        with patch("app.api.avatars.get_gravatar", AsyncMock(return_value=image)) as fetch:
            await get_user_avatar(uuid.uuid4(), _request(), current_user=self._user(), db=db)

        fetch.assert_awaited_once_with("teammate@example.com")

    async def test_matching_etag_returns_304_without_body(self) -> None:
        image = GravatarImage(content=_PNG, content_type="image/png", etag='"abc"')
        user = self._user()
        with patch("app.api.avatars.get_gravatar", AsyncMock(return_value=image)):
            response = await get_user_avatar(
                user.id, _request('"abc"'), current_user=user, db=AsyncMock()
            )

        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.body, b"")

    async def test_no_gravatar_is_a_cacheable_404(self) -> None:
        user = self._user()
        with patch("app.api.avatars.get_gravatar", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await get_user_avatar(user.id, _request(), current_user=user, db=AsyncMock())

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("private", (ctx.exception.headers or {})["Cache-Control"])

    async def test_unknown_user_is_404_without_calling_gravatar(self) -> None:
        db = self._db_returning_email(None)
        with patch("app.api.avatars.get_gravatar", AsyncMock()) as fetch:
            with self.assertRaises(HTTPException) as ctx:
                await get_user_avatar(uuid.uuid4(), _request(), current_user=self._user(), db=db)

        self.assertEqual(ctx.exception.status_code, 404)
        fetch.assert_not_awaited()
