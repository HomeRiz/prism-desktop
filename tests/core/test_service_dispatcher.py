from unittest.mock import AsyncMock

import pytest

from core import service_dispatcher as sd
from core.service_dispatcher import ServiceDispatcher


@pytest.fixture
def clock(monkeypatch):
    state = {"now": 1000.0}
    monkeypatch.setattr(sd, "time", type("Clock", (), {"time": staticmethod(lambda: state["now"])}))
    return state


@pytest.fixture
def ha():
    client = AsyncMock()
    client.get_state.return_value = None
    return client


@pytest.fixture
def dispatcher(ha, clock):
    return ServiceDispatcher(ha)


def last_call(ha):
    return ha.call_service.await_args


@pytest.mark.parametrize("config,expected", [
    ({"entity_id": "switch.a"}, ("homeassistant", "toggle", "switch.a", {})),
    ({"type": "light", "entity_id": "light.a"}, ("homeassistant", "toggle", "light.a", {})),
    ({"type": "curtain", "entity_id": "cover.a"}, ("cover", "toggle", "cover.a", {})),
    ({"type": "scene", "entity_id": "scene.a"}, ("scene", "turn_on", "scene.a", {})),
    ({"type": "script", "entity_id": "script.a"}, ("script", "turn_on", "script.a", {})),
    ({"type": "automation", "entity_id": "automation.a"}, ("automation", "toggle", "automation.a", {})),
    ({"type": "automation", "entity_id": "automation.a", "action": "trigger"},
     ("automation", "trigger", "automation.a", {})),
    ({"type": "media_player", "entity_id": "media_player.a"},
     ("media_player", "media_play_pause", "media_player.a", {})),
    ({"type": "media_player", "entity_id": "media_player.a", "action": "media_next_track"},
     ("media_player", "media_next_track", "media_player.a", {})),
    ({"entity_id": "input_number.a", "action": "set_input_number", "value": 4.5},
     ("input_number", "set_value", "input_number.a", {"value": 4.5})),
    ({"entity_id": "input_number.a", "action": "set_input_number"},
     ("input_number", "set_value", "input_number.a", {"value": 0.0})),
])
async def test_button_click_routes_to_expected_service(dispatcher, ha, config, expected):
    await dispatcher.handle_button_click(config)
    ha.call_service.assert_awaited_once_with(*expected)


async def test_click_without_entity_id_does_nothing(dispatcher, ha):
    await dispatcher.handle_button_click({"type": "switch"})
    await dispatcher.handle_button_click({"entity_id": ""})
    ha.call_service.assert_not_awaited()


async def test_script_with_variables_calls_script_by_name(dispatcher, ha):
    await dispatcher.handle_button_click(
        {"type": "script", "entity_id": "script.movie_night", "script_variables": {"level": 3}})
    ha.call_service.assert_awaited_once_with("script", "movie_night", None, {"level": 3})


async def test_script_name_only_strips_leading_prefix(dispatcher, ha):
    await dispatcher.handle_button_click(
        {"type": "script", "entity_id": "script.script.x", "script_variables": {"a": 1}})
    assert last_call(ha).args[1] == "script.x"


@pytest.mark.parametrize("service,expected", [
    ("light.turn_on", ("light", "turn_on")),
    ("turn_off", ("homeassistant", "turn_off")),
    ("climate.set_temperature", ("climate", "set_temperature")),
    ("a.b.c", ("a", "b.c")),
])
async def test_explicit_service_overrides_type_routing(dispatcher, ha, service, expected):
    await dispatcher.handle_button_click(
        {"type": "curtain", "entity_id": "x.y", "service": service, "service_data": {"k": 1}})
    ha.call_service.assert_awaited_once_with(*expected, "x.y", {"k": 1})
    ha.get_state.assert_not_awaited()


@pytest.mark.parametrize("action", ["lock", "unlock"])
async def test_lock_explicit_action_skips_state_lookup(dispatcher, ha, action):
    await dispatcher.handle_button_click({"type": "lock", "entity_id": "lock.a", "action": action})
    ha.call_service.assert_awaited_once_with("lock", action, "lock.a", {})
    ha.get_state.assert_not_awaited()


@pytest.mark.parametrize("current,service", [
    ("locked", "unlock"), ("unlocked", "lock"), ("jammed", "lock"),
])
async def test_lock_toggle_reverses_current_state(dispatcher, ha, current, service):
    ha.get_state.return_value = {"state": current}
    await dispatcher.handle_button_click({"type": "lock", "entity_id": "lock.a"})
    ha.call_service.assert_awaited_once_with("lock", service, "lock.a", {})


@pytest.mark.parametrize("state", [None, {}, {"state": None}])
async def test_lock_toggle_never_guesses_when_state_unreadable(dispatcher, ha, state):
    ha.get_state.return_value = state
    await dispatcher.handle_button_click({"type": "lock", "entity_id": "lock.a"})
    ha.call_service.assert_not_awaited()


async def test_lock_with_unknown_action_falls_back_to_state_toggle(dispatcher, ha):
    ha.get_state.return_value = {"state": "locked"}
    await dispatcher.handle_button_click({"type": "lock", "entity_id": "lock.a", "action": "open"})
    assert last_call(ha).args[1] == "unlock"


@pytest.mark.parametrize("kind,domain,active,start", [
    ("lawn_mower", "lawn_mower", ("mowing", "returning"), "start_mowing"),
    ("vacuum", "vacuum", ("cleaning", "returning"), "start"),
])
async def test_pause_when_active_otherwise_start(dispatcher, ha, clock, kind, domain, active, start):
    for state in active:
        clock["now"] += 10
        ha.get_state.return_value = {"state": state}
        await dispatcher.handle_button_click({"type": kind, "entity_id": f"{domain}.a"})
        assert last_call(ha).args[:2] == (domain, "pause")
    for state in ("docked", "paused"):
        clock["now"] += 10
        ha.get_state.return_value = {"state": state}
        await dispatcher.handle_button_click({"type": kind, "entity_id": f"{domain}.a"})
        assert last_call(ha).args[:2] == (domain, start)


@pytest.mark.parametrize("kind,domain,start", [
    ("lawn_mower", "lawn_mower", "start_mowing"), ("vacuum", "vacuum", "start"),
])
async def test_missing_state_is_treated_as_docked(dispatcher, ha, kind, domain, start):
    await dispatcher.handle_button_click({"type": kind, "entity_id": f"{domain}.a"})
    assert last_call(ha).args[:2] == (domain, start)


async def test_second_click_inside_cooldown_is_dropped(dispatcher, ha, clock):
    config = {"entity_id": "switch.a"}
    await dispatcher.handle_button_click(config)
    clock["now"] += 0.4
    await dispatcher.handle_button_click(config)
    assert ha.call_service.await_count == 1


async def test_click_after_cooldown_is_processed(dispatcher, ha, clock):
    config = {"entity_id": "switch.a"}
    await dispatcher.handle_button_click(config)
    clock["now"] += 0.5
    await dispatcher.handle_button_click(config)
    assert ha.call_service.await_count == 2


async def test_cooldown_is_tracked_per_entity(dispatcher, ha):
    await dispatcher.handle_button_click({"entity_id": "switch.a"})
    await dispatcher.handle_button_click({"entity_id": "switch.b"})
    assert ha.call_service.await_count == 2


async def test_skip_debounce_bypasses_cooldown(dispatcher, ha):
    config = {"entity_id": "light.a", "skip_debounce": True}
    await dispatcher.handle_button_click(config)
    await dispatcher.handle_button_click(config)
    assert ha.call_service.await_count == 2


async def test_debounced_click_does_not_query_state(dispatcher, ha):
    config = {"type": "lock", "entity_id": "lock.a"}
    ha.get_state.return_value = {"state": "locked"}
    await dispatcher.handle_button_click(config)
    await dispatcher.handle_button_click(config)
    assert ha.get_state.await_count == 1


async def test_volume_scroll_sets_volume_level(dispatcher, ha):
    await dispatcher.handle_volume_scroll("media_player.tv", 0.35)
    ha.call_service.assert_awaited_once_with(
        "media_player", "volume_set", "media_player.tv", {"volume_level": 0.35})


async def test_media_command_calls_media_player_service(dispatcher, ha):
    await dispatcher.handle_media_command("media_player.tv", "media_pause")
    ha.call_service.assert_awaited_once_with("media_player", "media_pause", "media_player.tv")


async def test_service_errors_propagate_to_caller(dispatcher, ha):
    ha.call_service.side_effect = RuntimeError("down")
    with pytest.raises(RuntimeError):
        await dispatcher.handle_button_click({"entity_id": "switch.a"})
