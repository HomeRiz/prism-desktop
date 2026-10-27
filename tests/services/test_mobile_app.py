import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from services import mobile_app, system_sensors

class FakeHA:
    def __init__(self):
        self.requests = []
        self.registration_status = 201
        self.registration_body = {"webhook_id": "abcdef1234567890"}
        self.webhook_status = 200
        self.webhook_delay = 0
        self.app = web.Application()
        self.app.router.add_post("/api/mobile_app/registrations", self.registrations)
        self.app.router.add_post("/api/webhook/{wid}", self.webhook)
        self.server = None

    async def registrations(self, request):
        self.requests.append(("registrations", dict(request.headers), await request.json()))
        return web.json_response(self.registration_body, status=self.registration_status)

    async def webhook(self, request):
        body = await request.json()
        self.requests.append(("webhook", dict(request.headers), body, request.match_info["wid"]))
        if self.webhook_delay:
            import asyncio
            await asyncio.sleep(self.webhook_delay)
        return web.json_response({}, status=self.webhook_status)

    def webhooks(self):
        return [r for r in self.requests if r[0] == "webhook"]

    @property
    def url(self):
        return str(self.server.make_url("")).rstrip("/")

@pytest.fixture
async def ha():
    fake = FakeHA()
    fake.server = TestServer(fake.app)
    await fake.server.start_server()
    yield fake
    await fake.server.close()

def make_config(**mobile):
    return {"mobile_app": dict(mobile)} if mobile else {}

async def test_registration_posts_payload_with_bearer_token(ha):
    saved = []
    config = {}
    webhook = await mobile_app.register_mobile_app(ha.url, "tok-123", config, lambda: saved.append(1))
    assert webhook == "abcdef1234567890"
    kind, headers, payload = ha.requests[0]
    assert headers["Authorization"] == "Bearer tok-123"
    assert payload["app_id"] == mobile_app.APP_ID
    assert payload["supports_encryption"] is False
    assert payload["app_data"] == {"push_websocket_channel": True}
    assert payload["device_id"] == config["mobile_app"]["device_id"]
    assert len(payload["device_id"]) == 32 and "-" not in payload["device_id"]
    assert config["mobile_app"]["webhook_id"] == webhook
    assert saved == [1]

async def test_registration_accepts_200_status(ha):
    ha.registration_status = 200
    webhook = await mobile_app.register_mobile_app(ha.url, "t", {}, lambda: None)
    assert webhook == "abcdef1234567890"

async def test_registration_tolerates_trailing_slash(ha):
    webhook = await mobile_app.register_mobile_app(ha.url + "/", "t", {}, lambda: None)
    assert webhook

async def test_registration_reuses_existing_device_id(ha):
    config = {"mobile_app": {"device_id": "fixeddevice"}}
    await mobile_app.register_mobile_app(ha.url, "t", config, lambda: None)
    assert ha.requests[0][2]["device_id"] == "fixeddevice"
    assert config["mobile_app"]["device_id"] == "fixeddevice"

async def test_registration_missing_webhook_id_in_response(ha):
    ha.registration_body = {}
    saved = []
    config = {}
    assert await mobile_app.register_mobile_app(ha.url, "t", config, lambda: saved.append(1)) is None
    assert "webhook_id" not in config["mobile_app"]
    assert saved == []

async def test_registration_conflict_clears_local_webhook(ha):
    ha.registration_status = 409
    saved = []
    config = {}
    assert await mobile_app.register_mobile_app(ha.url, "t", config, lambda: saved.append(1)) is None
    assert "webhook_id" not in config["mobile_app"]
    assert saved == [1]

@pytest.mark.parametrize("status", [401, 403, 500])
async def test_registration_http_failure_returns_none(ha, status):
    ha.registration_status = status
    assert await mobile_app.register_mobile_app(ha.url, "t", {}, lambda: None) is None

@pytest.mark.parametrize("url,token", [("", "t"), ("http://x", ""), ("", "")])
async def test_registration_skipped_without_url_or_token(url, token):
    assert await mobile_app.register_mobile_app(url, token, {}, lambda: None) is None

async def test_registration_unreachable_server_returns_none():
    assert await mobile_app.register_mobile_app("http://127.0.0.1:1", "t", {}, lambda: None) is None

async def test_existing_valid_webhook_is_refreshed_not_reregistered(ha):
    config = make_config(webhook_id="existingwebhook")
    result = await mobile_app.register_mobile_app(ha.url, "t", config, lambda: None)
    assert result == "existingwebhook"
    assert [r[0] for r in ha.requests] == ["webhook"]
    body = ha.requests[0][2]
    assert body["type"] == "update_registration"
    assert body["data"]["app_data"] == {"push_websocket_channel": True}
    assert body["data"]["app_version"] == mobile_app.APP_VERSION
    assert "Authorization" not in ha.requests[0][1]

@pytest.mark.parametrize("status", [404, 410])
async def test_dead_webhook_triggers_fresh_registration(ha, status):
    ha.webhook_status = status
    saved = []
    config = make_config(webhook_id="deadwebhook", device_id="dev1")
    result = await mobile_app.register_mobile_app(ha.url, "t", config, lambda: saved.append(1))
    assert result == "abcdef1234567890"
    assert config["mobile_app"]["webhook_id"] == "abcdef1234567890"
    assert [r[0] for r in ha.requests] == ["webhook", "registrations"]
    assert len(saved) == 2

async def test_dead_webhook_without_token_clears_and_returns_none(ha):
    ha.webhook_status = 404
    config = make_config(webhook_id="deadwebhook")
    assert await mobile_app.register_mobile_app(ha.url, "", config, lambda: None) is None
    assert "webhook_id" not in config["mobile_app"]

async def test_server_error_on_refresh_keeps_registration(ha):
    ha.webhook_status = 500
    config = make_config(webhook_id="existingwebhook")
    assert await mobile_app.register_mobile_app(ha.url, "t", config, lambda: None) == "existingwebhook"

async def test_network_error_on_refresh_keeps_registration():
    config = make_config(webhook_id="existingwebhook")
    result = await mobile_app.register_mobile_app("http://127.0.0.1:1", "t", config, lambda: None)
    assert result == "existingwebhook"

async def test_send_location_update_payload(ha):
    location = {"gps": [1.5, 2.5], "gps_accuracy": 12}
    assert await mobile_app.send_location_update(ha.url, "wh1", location) is True
    _, headers, body, wid = ha.webhooks()[0]
    assert wid == "wh1"
    assert body == {"type": "update_location", "data": location}
    assert "Authorization" not in headers

async def test_send_location_update_failure_status(ha):
    ha.webhook_status = 410
    assert await mobile_app.send_location_update(ha.url, "wh1", {}) is False

async def test_send_location_update_unreachable():
    assert await mobile_app.send_location_update("http://127.0.0.1:1", "wh", {}) is False

async def test_notification_action_event_payload(ha):
    event = {"action": "OPEN", "device_id": "d", "device_name": "n"}
    assert await mobile_app.fire_notification_action_event(ha.url, "wh1", event) is True
    body = ha.webhooks()[0][2]
    assert body == {
        "type": "fire_event",
        "data": {"event_type": "mobile_app_notification_action", "event_data": event},
    }

async def test_notification_action_event_failure(ha):
    ha.webhook_status = 500
    assert await mobile_app.fire_notification_action_event(ha.url, "wh1", {}) is False

async def test_notification_action_event_unreachable():
    assert await mobile_app.fire_notification_action_event("http://127.0.0.1:1", "w", {}) is False

def test_action_event_data_merges_action_data():
    data = mobile_app.build_notification_action_event_data("A", {"room": "kitchen"}, "d", "n")
    assert data == {"room": "kitchen", "action": "A", "device_id": "d", "device_name": "n"}

def test_action_event_data_reserved_keys_win_over_collisions():
    data = mobile_app.build_notification_action_event_data(
        "REAL", {"action": "spoof", "device_id": "spoof", "device_name": "spoof"}, "d", "n"
    )
    assert data == {"action": "REAL", "device_id": "d", "device_name": "n"}

@pytest.mark.parametrize("bad", [None, "x", ["a"], 5])
def test_action_event_data_ignores_non_dict_action_data(bad):
    data = mobile_app.build_notification_action_event_data("A", bad, "d", "n")
    assert data == {"action": "A", "device_id": "d", "device_name": "n"}

def test_action_event_data_does_not_mutate_input():
    source = {"k": 1}
    mobile_app.build_notification_action_event_data("A", source, "d", "n")
    assert source == {"k": 1}

def test_sensor_state_payload_filters_unknown_ids():
    payload = mobile_app.build_sensor_state_payload({"cpu_usage": 5, "nope": 1, "battery_charging": True})
    assert payload == [
        {"type": "sensor", "unique_id": "cpu_usage", "state": 5},
        {"type": "binary_sensor", "unique_id": "battery_charging", "state": True},
    ]

def test_sensor_state_payload_empty():
    assert mobile_app.build_sensor_state_payload({}) == []

async def test_update_sensor_states_posts_payload(ha):
    assert await mobile_app.update_sensor_states(ha.url, "wh", {"logged_in": "logged-in"}) is True
    body = ha.webhooks()[0][2]
    assert body["type"] == "update_sensor_states"
    assert body["data"] == [{"type": "sensor", "unique_id": "logged_in", "state": "logged-in"}]

async def test_update_sensor_states_unknown_ids_skip_request(ha):
    assert await mobile_app.update_sensor_states(ha.url, "wh", {"bogus": 1}) is False
    assert ha.requests == []

async def test_update_sensor_states_failure_status(ha):
    ha.webhook_status = 500
    assert await mobile_app.update_sensor_states(ha.url, "wh", {"cpu_usage": 1}) is False

async def test_update_sensor_states_unreachable():
    assert await mobile_app.update_sensor_states("http://127.0.0.1:1", "wh", {"cpu_usage": 1}) is False

async def test_register_sensors_skips_unavailable_optional_sensors(ha, monkeypatch):
    monkeypatch.setattr(system_sensors, "collect", lambda ids: {"battery_level": 77.0, "disk_usage": 40.5})
    await mobile_app.register_sensors(ha.url, "wh")
    registered = {r[2]["data"]["unique_id"]: r[2]["data"] for r in ha.webhooks()}
    assert all(r[2]["type"] == "register_sensor" for r in ha.webhooks())
    assert {"logged_in", "cpu_usage", "ram_usage", "battery_level", "disk_usage"} == set(registered)
    assert registered["battery_level"]["state"] == 77.0
    assert registered["disk_usage"]["state"] == 40.5
    assert "cpu_temperature" not in registered

async def test_register_sensors_requests_every_optional_sensor_probe(ha, monkeypatch):
    seen = []
    monkeypatch.setattr(system_sensors, "collect", lambda ids: seen.extend(ids) or {})
    await mobile_app.register_sensors(ha.url, "wh")
    assert set(seen) == set(system_sensors.COLLECTORS)

async def test_register_sensors_does_not_mutate_sensor_definitions(ha, monkeypatch):
    monkeypatch.setattr(system_sensors, "collect", lambda ids: {"battery_level": 55.0})
    await mobile_app.register_sensors(ha.url, "wh")
    battery = next(s for s in mobile_app.SENSORS if s["unique_id"] == "battery_level")
    assert battery["state"] is None

async def test_register_sensors_swallows_connection_errors(monkeypatch):
    monkeypatch.setattr(system_sensors, "collect", lambda ids: {})
    await mobile_app.register_sensors("http://127.0.0.1:1", "wh")

async def test_register_sensors_continues_after_http_failure(ha, monkeypatch):
    monkeypatch.setattr(system_sensors, "collect", lambda ids: {})
    ha.webhook_status = 500
    await mobile_app.register_sensors(ha.url, "wh")
    assert len(ha.webhooks()) == 3

def test_sensor_definitions_are_unique_and_json_serialisable():
    ids = [s["unique_id"] for s in mobile_app.SENSORS]
    assert len(ids) == len(set(ids))
    json.dumps(mobile_app.SENSORS)

def test_system_metrics_use_psutil(monkeypatch):
    monkeypatch.setattr(mobile_app.psutil, "cpu_percent", lambda interval=None: 12.345)

    class Mem:
        percent = 55.55

    monkeypatch.setattr(mobile_app.psutil, "virtual_memory", lambda: Mem())
    assert mobile_app.get_system_metrics() == {"cpu_usage": 12.3, "ram_usage": 55.5}

def test_device_name_falls_back_when_hostname_fails(monkeypatch):
    def boom():
        raise OSError

    monkeypatch.setattr(mobile_app.socket, "gethostname", boom)
    assert mobile_app._get_device_name() == "Prism Desktop"

def test_device_id_is_generated_once_and_stable():
    config = {}
    first = mobile_app._get_or_create_device_id(config)
    assert mobile_app._get_or_create_device_id(config) == first
