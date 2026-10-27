import asyncio

import aiohttp
import pytest

from core import ha_websocket as hw
from core.ha_websocket import HAWebSocket

REAL_SLEEP = asyncio.sleep


async def until(predicate, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await REAL_SLEEP(0.01)


@pytest.fixture
def client():
    return HAWebSocket("http://ha", "tok")


@pytest.fixture
def rec(client, make_recorder):
    return make_recorder(client)


def state_event(entity_id, new_state, msg_id=1):
    return {"type": "event", "id": msg_id, "event": {
        "event_type": "state_changed", "data": {"entity_id": entity_id, "new_state": new_state}}}


@pytest.fixture
async def live(ws_url, ws_script, make_recorder, fast_timeouts):
    ws_script.close_after = lambda n: False
    client = HAWebSocket(ws_url, "good-token")
    rec = make_recorder(client)
    task = asyncio.create_task(client.connect())
    await until(lambda: rec.connected == 1 or rec.errors)
    yield client, rec
    if client._ws is not None and not client._ws.closed:
        await client._ws.close()
    await asyncio.wait_for(task, 5)


async def test_handshake_sends_token_and_subscriptions(ws_url, ws_script, make_recorder):
    client = HAWebSocket(ws_url + "/", "good-token")
    rec = make_recorder(client)
    await client.connect()
    assert rec.connected == 1 and rec.disconnected == 1 and rec.errors == []
    auth, first, second = ws_script.received
    assert auth == {"type": "auth", "access_token": "good-token"}
    assert (first["id"], first["event_type"]) == (1, "state_changed")
    assert (second["id"], second["event_type"]) == (2, "call_service")


async def test_rejected_token_emits_error_and_marks_auth_failed(ws_url, ws_script, make_recorder):
    client = HAWebSocket(ws_url, "wrong")
    rec = make_recorder(client)
    await client.connect()
    assert rec.connected == 0
    assert rec.errors == ["Authentication failed: Invalid password"]
    assert client._auth_failed is True
    assert rec.disconnected == 1
    assert len(ws_script.received) == 1


async def test_unexpected_first_message_is_an_error(ws_url, ws_script, make_recorder):
    ws_script.hello = "something_else"
    client = HAWebSocket(ws_url, "good-token")
    rec = make_recorder(client)
    await client.connect()
    assert rec.errors == ["Unexpected message type"]
    assert client._auth_failed is False
    assert rec.connected == 0


async def test_silent_server_times_out_with_readable_error(ws_url, ws_script, fast_timeouts, make_recorder):
    ws_script.hello = None
    client = HAWebSocket(ws_url, "good-token")
    rec = make_recorder(client)
    await client.connect()
    assert rec.errors == ["TimeoutError"]
    assert rec.disconnected == 1


@pytest.mark.parametrize("url,token", [("", "t"), ("http://h", ""), ("", "")])
async def test_missing_credentials_emit_error_without_connecting(url, token, make_recorder):
    client = HAWebSocket(url, token)
    rec = make_recorder(client)
    await client.connect()
    assert rec.errors == ["URL and token are required"]
    assert client._ws is None and client._session is None


@pytest.mark.parametrize("url,expected", [
    ("http://ha:8123", "ws://ha:8123/api/websocket"),
    ("https://ha.example", "wss://ha.example/api/websocket"),
])
async def test_url_scheme_is_mapped_to_websocket(monkeypatch, url, expected, make_recorder):
    seen = []

    async def fake_ws_connect(self, target, *a, **k):
        seen.append(target)
        raise aiohttp.ClientError("stop")

    monkeypatch.setattr(aiohttp.ClientSession, "ws_connect", fake_ws_connect)
    client = HAWebSocket(url, "t")
    rec = make_recorder(client)
    await client.connect()
    assert seen == [expected]
    assert rec.errors == ["stop"]


async def test_connection_refused_emits_error_and_disconnects(make_recorder):
    client = HAWebSocket("http://127.0.0.1:1", "t")
    rec = make_recorder(client)
    await client.connect()
    assert len(rec.errors) == 1 and rec.disconnected == 1


async def test_state_changes_are_dispatched_to_signal(ws_url, ws_script, make_recorder):
    ws_script.to_send = [state_event("light.a", {"state": "on"}), state_event("light.b", {"state": "off"})]
    client = HAWebSocket(ws_url, "good-token")
    rec = make_recorder(client)
    await client.connect()
    assert rec.states == [("light.a", {"state": "on"}), ("light.b", {"state": "off"})]


async def test_subscription_filter_limits_state_signals(ws_url, ws_script, make_recorder):
    ws_script.to_send = [state_event("light.a", {"state": "on"}), state_event("light.b", {"state": "off"})]
    client = HAWebSocket(ws_url, "good-token")
    client.subscribe_entity("light.b")
    rec = make_recorder(client)
    await client.connect()
    assert rec.states == [("light.b", {"state": "off"})]


async def test_removed_entity_with_null_new_state_emits_empty_dict(client, rec):
    await client._handle_message(state_event("light.gone", None))
    assert rec.states == [("light.gone", {})]


async def test_persistent_notification_state_change_emits_notification(client, rec):
    state = {"state": "fallback", "attributes": {"title": "Alert", "message": "Door open"}}
    await client._handle_message(state_event("persistent_notification.n1", state))
    assert rec.notifications == [{"title": "Alert", "message": "Door open"}]
    assert rec.states == [("persistent_notification.n1", state)]


async def test_persistent_notification_without_message_uses_state_text(client, rec):
    await client._handle_message(state_event("persistent_notification.n", {"state": "notifying"}))
    assert rec.notifications == [{"title": "Home Assistant", "message": "notifying"}]


def service_event(domain, service, data):
    return {"type": "event", "id": 2, "event": {
        "event_type": "call_service", "data": {"domain": domain, "service": service, "service_data": data}}}


async def test_persistent_notification_create_call_is_surfaced(client, rec):
    await client._handle_message(service_event("persistent_notification", "create", {"title": "T", "message": "M"}))
    assert rec.notifications == [{"title": "T", "message": "M"}]


async def test_irrelevant_events_emit_no_notification(client, rec):
    await client._handle_message(state_event("persistent_notification.n", None))
    await client._handle_message(service_event("persistent_notification", "create", {"title": "T"}))
    await client._handle_message(service_event("light", "turn_on", {"message": "x"}))
    assert rec.notifications == []


async def test_push_channel_event_merges_extra_data(ws_url, ws_script, make_recorder):
    ws_script.expected_subs = 3
    ws_script.to_send = [{"type": "event", "id": 3, "event": {
        "title": "Hi", "message": "Body", "data": {"image": "/x.png"}}}]
    client = HAWebSocket(ws_url, "good-token")
    client.set_webhook_id("hook-1")
    rec = make_recorder(client)
    await client.connect()
    push = ws_script.received[3]
    assert push["type"] == "mobile_app/push_notification_channel"
    assert push["webhook_id"] == "hook-1" and push["id"] == 3
    assert rec.notifications == [{"title": "Hi", "message": "Body", "image": "/x.png"}]


async def test_push_event_without_message_or_with_odd_data(client, rec):
    client._push_channel_id = 7
    await client._handle_message({"type": "event", "id": 7, "event": {"title": "x"}})
    await client._handle_message({"type": "event", "id": 7, "event": {"message": "m", "data": "oops"}})
    assert rec.notifications == [{"title": "Home Assistant", "message": "m"}]


async def test_invalid_json_from_server_emits_error_and_disconnects(ws_url, ws_script, make_recorder):
    ws_script.to_send = ["this is not json"]
    client = HAWebSocket(ws_url, "good-token")
    rec = make_recorder(client)
    await client.connect()
    assert len(rec.errors) == 1
    assert rec.disconnected == 1


async def test_idle_connection_sends_ping(live, ws_script):
    client, rec = live
    await until(lambda: any(m.get("type") == "ping" for m in ws_script.received))


async def test_request_stop_sets_flags_and_ids_increment(client):
    client._running = True
    client.request_stop()
    assert client._running is False and client._should_stop_loop is True
    assert [client._next_id(), client._next_id()] == [1, 2]


async def test_conversation_process_returns_result_payload(live, ws_script):
    async def reply(ws, data):
        if data["type"] == "conversation/process":
            await ws.send_json({"id": data["id"], "type": "result", "success": True,
                                "result": {"response": "ok", "conversation_id": "c1"}})

    ws_script.on_message = reply
    client, rec = live
    result = await client.conversation_process("lights on", conversation_id="c0", language="en")
    sent = [m for m in ws_script.received if m.get("type") == "conversation/process"][0]
    assert sent["text"] == "lights on" and sent["conversation_id"] == "c0" and sent["language"] == "en"
    assert result == {"response": "ok", "conversation_id": "c1"}
    assert client._pending_results == {}


async def test_conversation_process_failure_raises(live, ws_script):
    async def reply(ws, data):
        if data["type"] == "conversation/process":
            await ws.send_json({"id": data["id"], "type": "result", "success": False,
                                "error": {"message": "no agent"}})

    ws_script.on_message = reply
    client, rec = live
    with pytest.raises(RuntimeError, match="no agent"):
        await client.conversation_process("x")


async def test_conversation_process_times_out_and_clears_pending(live, ws_script):
    client, rec = live
    with pytest.raises(asyncio.TimeoutError):
        await client.conversation_process("x", timeout=0.1)
    assert client._pending_results == {}


async def test_disconnect_fails_pending_requests(live, ws_script):
    async def drop(ws, data):
        if data["type"] == "conversation/process":
            await ws.close()

    ws_script.on_message = drop
    client, rec = live
    with pytest.raises(ConnectionError):
        await client.conversation_process("x", timeout=5)


async def test_result_without_waiter_is_ignored(client, rec):
    await client._handle_message({"type": "result", "id": 99, "success": True})


async def test_assist_pipeline_streams_events_until_run_end(live, ws_script):
    async def run(ws, data):
        if data["type"] == "assist_pipeline/run":
            for event in ({"type": "run-start"}, {"type": "stt-end"}, {"type": "run-end"}):
                await ws.send_json({"id": data["id"], "type": "event", "event": event})

    ws_script.on_message = run
    client, rec = live
    events = [e async for e in client.run_assist_pipeline(conversation_id="c", sample_rate=8000)]
    assert [e["type"] for e in events] == ["run-start", "stt-end", "run-end"]
    sent = [m for m in ws_script.received if m.get("type") == "assist_pipeline/run"][0]
    assert sent["input"] == {"sample_rate": 8000} and sent["conversation_id"] == "c"
    assert client._pending_pipeline_runs == {}


async def test_assist_pipeline_rejected_command_yields_error_event(client):
    queue = asyncio.Queue()
    client._pending_pipeline_runs[5] = queue
    await client._handle_message({"type": "result", "id": 5, "success": False,
                                  "error": {"code": "nope", "message": "bad"}})
    assert await queue.get() == {"type": "error", "data": {"code": "nope", "message": "bad"}}
    await client._handle_message({"type": "result", "id": 5, "success": True})
    assert queue.empty()


async def test_requests_require_a_connection(client):
    with pytest.raises(ConnectionError):
        await client.conversation_process("x")
    with pytest.raises(ConnectionError):
        async for _ in client.run_assist_pipeline():
            pass


async def test_cleanup_signals_pipeline_listeners(client, rec):
    queue = asyncio.Queue()
    client._pending_pipeline_runs[1] = queue
    await client._cleanup()
    assert (await queue.get())["data"]["code"] == "disconnected"
    assert client._pending_pipeline_runs == {} and rec.disconnected == 1


async def test_stt_audio_is_prefixed_with_handler_id(live, ws_script):
    client, rec = live
    await client.send_stt_audio(4, b"\x01\x02")
    await client.end_stt_audio(4)
    await until(lambda: len(ws_script.binary) == 2)
    assert ws_script.binary == [b"\x04\x01\x02", b"\x04"]


async def test_sending_without_connection_is_a_noop(client):
    await client._send({"type": "x"})
    await client.send_stt_audio(1, b"x")
    await client.end_stt_audio(1)


async def drive_loop(client, stop_at, each=None):
    calls = []

    async def fake_connect():
        calls.append(len(calls) + 1)
        if len(calls) == stop_at:
            client.request_stop()
        if each:
            each(client, len(calls))

    client.connect = fake_connect
    await client.run_reconnect_loop()
    return calls


async def test_reconnect_backoff_doubles_between_attempts(client, rec, fast_sleep):
    assert await drive_loop(client, 3) == [1, 2, 3]
    assert rec.errors == ["Disconnected. Reconnecting in 1s...", "Disconnected. Reconnecting in 2s..."]


async def test_reconnect_backoff_is_capped_at_thirty_seconds(client, rec, fast_sleep):
    await drive_loop(client, 9)
    assert rec.errors[-1] == "Disconnected. Reconnecting in 30s..."
    assert "Reconnecting in 60s" not in " ".join(rec.errors)


async def test_reconnect_backoff_resets_after_long_connection(client, rec, fast_sleep, monkeypatch):
    clock = {"now": 0.0}
    monkeypatch.setattr(hw, "time", type("Clock", (), {"time": staticmethod(lambda: clock["now"])}))
    await drive_loop(client, 4, lambda c, n: clock.update(now=clock["now"] + 20))
    assert set(rec.errors) == {"Disconnected. Reconnecting in 1s..."}


async def test_reconnect_stops_after_authentication_failure(client, rec, fast_sleep):
    calls = await drive_loop(client, 99, lambda c, n: setattr(c, "_auth_failed", True))
    assert calls == [1] and rec.errors == []


async def test_reconnect_survives_unexpected_exceptions(client, fast_sleep):
    def explode(c, n):
        raise RuntimeError("boom")

    assert await drive_loop(client, 3, explode) == [1, 2, 3]


async def test_reconnect_loop_exits_on_cancellation(client):
    async def hang():
        await asyncio.Event().wait()

    client.connect = hang
    task = asyncio.create_task(client.run_reconnect_loop())
    await REAL_SLEEP(0.05)
    task.cancel()
    await asyncio.wait_for(task, 2)


async def test_reconnect_loop_reconnects_to_real_server(ws_url, ws_script, fast_sleep, make_recorder):
    ws_script.close_after = lambda n: n == 1
    client = HAWebSocket(ws_url, "good-token")
    rec = make_recorder(client)
    task = asyncio.create_task(client.run_reconnect_loop())
    await until(lambda: rec.connected == 2)
    client.request_stop()
    await client._ws.close()
    await asyncio.wait_for(task, 5)
    assert ws_script.connections == 2
    assert any("Reconnecting" in e for e in rec.errors)

