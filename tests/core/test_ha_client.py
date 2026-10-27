import asyncio
import json

import aiohttp
import pytest
from aiohttp import web

from core.ha_client import HAClient

TOKEN = "tok-123"


@pytest.fixture
async def ha(start_server, make_ha_app):
    log = []
    server = await start_server(make_ha_app(log))
    client = HAClient(f"http://127.0.0.1:{server.port}/", TOKEN)
    yield client, log
    await client.close()


def test_url_trailing_slashes_are_stripped():
    assert HAClient("http://h:8123///", "t").url == "http://h:8123"


def test_headers_carry_bearer_token():
    assert HAClient("http://h", "abc").headers == {
        "Authorization": "Bearer abc", "Content-Type": "application/json"}


async def test_configure_updates_credentials_and_drops_session(ha):
    client, log = ha
    await client.get_config()
    old = client._session
    client.configure(client.url + "/", "new-token")
    assert client.token == "new-token"
    assert not client.url.endswith("/")
    assert client._session is None
    await asyncio.sleep(0)
    await old.close()
    await client.get_config()
    assert log[-1][2]["Authorization"] == "Bearer new-token"


def test_configure_without_running_loop_is_safe():
    client = HAClient("http://h", "t")

    class FakeSession:
        closed = False

    client._session = FakeSession()
    client.configure("http://other/", "t2")
    assert client._session is None and client.url == "http://other"


async def test_test_connection_success_sends_auth_header(ha):
    client, log = ha
    assert await client.test_connection() == (True, "Connected")
    assert log[0][2]["Authorization"] == f"Bearer {TOKEN}"


async def test_test_connection_requires_url_and_token():
    assert await HAClient("", "t").test_connection() == (False, "URL and token are required")
    assert await HAClient("http://h", "").test_connection() == (False, "URL and token are required")


async def test_test_connection_reports_invalid_token(start_server):
    async def unauthorized(request):
        return web.Response(status=401)

    app = web.Application()
    app.router.add_get("/api/", unauthorized)
    server = await start_server(app)
    ok, message = await HAClient(f"http://127.0.0.1:{server.port}", "bad").test_connection()
    assert (ok, message) == (False, "Invalid access token")


async def test_test_connection_reports_other_http_status(start_server):
    async def broken(request):
        return web.Response(status=503)

    app = web.Application()
    app.router.add_get("/api/", broken)
    server = await start_server(app)
    ok, message = await HAClient(f"http://127.0.0.1:{server.port}", "t").test_connection()
    assert (ok, message) == (False, "HTTP 503")


async def test_test_connection_timeout_message(ha, monkeypatch):
    client, _ = ha

    def slow(self, *a, **k):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(aiohttp.ClientSession, "get", slow)
    assert await client.test_connection() == (False, "Connection timed out")


async def test_test_connection_refused_is_connection_error():
    ok, message = await HAClient("http://127.0.0.1:1", "t").test_connection()
    assert ok is False and message.startswith("Connection error:")


async def test_test_connection_unexpected_exception_is_reported(ha, monkeypatch):
    client, _ = ha

    def explode(self, *a, **k):
        raise ValueError("kaboom")

    monkeypatch.setattr(aiohttp.ClientSession, "get", explode)
    assert await client.test_connection() == (False, "Error: kaboom")


async def test_test_connection_uses_current_credentials_not_pooled_session(ha):
    client, log = ha
    await client.get_entities()
    client.token = "rotated"
    await client.test_connection()
    assert log[-1][2]["Authorization"] == "Bearer rotated"


async def test_untrusted_tls_certificate_is_rejected(make_ha_app, self_signed):
    from aiohttp.test_utils import TestServer

    log = []
    server = TestServer(make_ha_app(log), host="127.0.0.1", ssl=self_signed)
    await server.start_server()
    try:
        ok, message = await HAClient(f"https://127.0.0.1:{server.port}", TOKEN).test_connection()
    finally:
        await server.close()
    assert ok is False
    assert message.startswith("Connection error:")
    assert log == []


async def test_get_entities_returns_list(ha):
    client, log = ha
    assert await client.get_entities() == [{"entity_id": "light.a", "state": "on"}]
    assert log[0][1] == "/api/states"
    assert log[0][2]["Authorization"] == f"Bearer {TOKEN}"


async def test_get_entities_unreachable_returns_empty_list():
    assert await HAClient("http://127.0.0.1:1", "t").get_entities() == []


async def test_get_config_success_and_unreachable_host(ha):
    client, _ = ha
    assert await client.get_config() == {"version": "2024.1"}
    other = HAClient("http://127.0.0.1:1", "t")
    assert await other.get_config() is None


async def test_get_state_returns_dict(ha):
    client, _ = ha
    assert (await client.get_state("light.a"))["state"] == "on"


async def test_get_state_404_returns_none(ha):
    client, _ = ha
    assert await client.get_state("sensor.missing") is None


async def test_get_state_bad_json_returns_none(ha):
    client, _ = ha
    assert await client.get_state("sensor.bad") is None


async def test_call_service_success_posts_payload_with_entity(ha):
    client, log = ha
    assert await client.call_service("light", "turn_on", "light.a", {"brightness": 5}) is True
    method, path, _, body = log[0]
    assert (method, path) == ("POST", "/api/services/light/turn_on")
    assert json.loads(body) == {"brightness": 5, "entity_id": "light.a"}


async def test_call_service_without_entity_or_data_sends_empty_object(ha):
    client, log = ha
    assert await client.call_service("homeassistant", "restart") is True
    assert log[0][3] == b"{}"


async def test_call_service_server_error_returns_false(ha):
    client, _ = ha
    assert await client.call_service("light", "fail", "light.a") is False


async def test_call_service_connection_error_returns_false():
    assert await HAClient("http://127.0.0.1:1", "t").call_service("a", "b") is False


async def test_call_service_timeout_returns_false(ha, monkeypatch):
    client, _ = ha

    def slow(self, *a, **k):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(aiohttp.ClientSession, "post", slow)
    assert await client.call_service("a", "b") is False


async def test_weather_forecast_extracts_entity_forecast(ha):
    client, log = ha
    assert await client.get_weather_forecast("weather.home", "hourly") == [{"temp": 1}]
    assert "return_response=true" in log[0][1]


async def test_weather_forecast_failure_returns_empty_list():
    assert await HAClient("http://127.0.0.1:1", "t").get_weather_forecast("weather.x") == []


async def test_camera_image_bytes(ha):
    client, _ = ha
    assert await client.get_camera_image("camera.door") == b"\xff\xd8jpeg"


async def test_camera_image_failure_returns_none():
    assert await HAClient("http://127.0.0.1:1", "t").get_camera_image("camera.x") is None


async def test_close_is_idempotent_and_closes_sessions(ha):
    client, _ = ha
    await client.get_config()
    session = client._session
    await client.close()
    await client.close()
    assert session.closed and client._session is None


async def test_session_is_reused_between_calls(ha):
    client, _ = ha
    await client.get_config()
    first = client._session
    await client.get_entities()
    assert client._session is first


async def test_anonymous_session_has_no_auth_and_dummy_cookie_jar():
    client = HAClient("http://h", "secret")
    session = await client._get_anon_session()
    try:
        assert "Authorization" not in session.headers
        assert isinstance(session.cookie_jar, aiohttp.DummyCookieJar)
    finally:
        await client.close()


@pytest.mark.parametrize("raw", [
    "", None, 123, "http://h/a\x00b", "http://h/a\nb", "/a\\b", "ftp://other/x", "javascript:alert(1)",
    "http://user:pw@other/x", "file:///etc/passwd",
])
def test_resolve_media_url_rejects_unusable_input(raw):
    assert HAClient("http://ha.local:8123", "t").resolve_media_url(raw) is None


@pytest.mark.parametrize("base", ["", "ftp://ha", "http://u:p@ha", "not a url"])
def test_resolve_media_url_rejects_bad_base_url(base):
    assert HAClient(base, "t").resolve_media_url("/api/x") is None


def test_resolve_relative_path_is_same_origin():
    url, same = HAClient("http://ha.local:8123", "t").resolve_media_url("/api/img/1")
    assert str(url) == "http://ha.local:8123/api/img/1" and same is True


def test_resolve_keeps_subpath_prefix():
    url, same = HAClient("https://example.com/ha", "t").resolve_media_url("/api/img")
    assert str(url) == "https://example.com/ha/api/img" and same is True


def test_resolve_absolute_same_origin_url():
    _, same = HAClient("http://ha.local:8123", "t").resolve_media_url("http://ha.local:8123/x?y=1")
    assert same is True


def test_resolve_foreign_host_is_not_same_origin():
    _, same = HAClient("http://ha.local:8123", "t").resolve_media_url("http://cdn.example.com/a.jpg")
    assert same is False


def test_resolve_different_port_or_scheme_is_not_same_origin():
    client = HAClient("http://ha.local:8123", "t")
    assert client.resolve_media_url("http://ha.local:9000/a")[1] is False
    assert client.resolve_media_url("https://ha.local:8123/a")[1] is False


def test_resolve_protocol_relative_inherits_scheme_but_not_host():
    url, same = HAClient("https://ha.local", "t").resolve_media_url("//evil.example/a")
    assert str(url) == "https://evil.example/a" and same is False


def test_resolve_lookalike_host_is_foreign():
    _, same = HAClient("http://ha.local", "t").resolve_media_url("http://ha.local.evil.com/a")
    assert same is False


def test_resolve_strips_fragment_and_whitespace():
    url, _ = HAClient("http://ha.local", "t").resolve_media_url("  http://ha.local/a#frag ")
    assert str(url) == "http://ha.local/a"


async def test_fetch_media_same_origin_uses_token(ha):
    client, log = ha
    assert await client.fetch_media("/api/img/1") == b"PNGDATA"
    assert log[0][2]["Authorization"] == f"Bearer {TOKEN}"


async def test_fetch_media_foreign_origin_sends_no_credentials(start_server, make_ha_app, ha):
    client, _ = ha
    foreign_log = []
    foreign = await start_server(make_ha_app(foreign_log))
    client.url = "http://localhost:1"
    data = await client.fetch_media(f"http://127.0.0.1:{foreign.port}/api/img/1")
    assert data == b"PNGDATA"
    assert "Authorization" not in foreign_log[0][2]


async def test_fetch_media_same_origin_does_not_follow_redirects(ha):
    client, log = ha
    assert await client.fetch_media("/api/redirect") is None
    assert [entry[1] for entry in log] == ["/api/redirect"]


async def test_fetch_media_rejects_oversized_body(ha):
    client, _ = ha
    assert await client.fetch_media("/api/big") is None


async def test_fetch_media_non_200_returns_none(ha):
    client, _ = ha
    assert await client.fetch_media("/api/teapot") is None


async def test_fetch_media_rejects_invalid_url_without_request(ha):
    client, log = ha
    assert await client.fetch_media("javascript:alert(1)") is None
    assert log == []


async def test_fetch_media_network_error_does_not_log_url(caplog):
    client = HAClient("http://127.0.0.1:1", "t")
    with caplog.at_level("ERROR"):
        assert await client.fetch_media("/api/img?token=SECRET") is None
    await client.close()
    assert "SECRET" not in caplog.text


async def test_get_media_image_empty_path_returns_none(ha):
    client, log = ha
    assert await client.get_media_image("") is None
    assert log == []


async def test_get_entity_image_fetches_state_then_picture(ha):
    client, log = ha
    assert await client.get_entity_image("image.cam") == b"PNGDATA"
    assert [entry[1] for entry in log] == ["/api/states/image.cam", "/api/img/1"]


async def test_get_entity_image_uses_supplied_state(ha):
    client, log = ha
    state = {"attributes": {"entity_picture": "/api/img/1"}}
    assert await client.get_entity_image("image.cam", state) == b"PNGDATA"
    assert [entry[1] for entry in log] == ["/api/img/1"]


async def test_get_entity_image_without_picture_returns_none(ha):
    client, _ = ha
    assert await client.get_entity_image("image.cam", {"attributes": {}}) is None
    assert await client.get_entity_image("image.cam", {}) is None


@pytest.mark.xfail(strict=True, reason="call_service writes entity_id into the caller's data dict")
async def test_call_service_does_not_mutate_callers_data(ha):
    client, _ = ha
    data = {"brightness": 5}
    await client.call_service("light", "turn_on", "light.a", data)
    assert data == {"brightness": 5}
