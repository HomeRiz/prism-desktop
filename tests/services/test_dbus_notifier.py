import pytest


@pytest.fixture
def dn(fake_dbus_modules, load_service):
    return load_service("dbus_notifier")


@pytest.fixture
def d(fake_dbus_modules):
    return fake_dbus_modules


def notify_responder(d, caps=("actions", "body"), nid=11, notify_error=None):
    def responder(msg):
        if msg.member == "GetCapabilities":
            return d.reply([list(caps)])
        if msg.member == "AddMatch":
            return d.reply()
        if msg.member == "Notify":
            return d.error_reply(notify_error) if notify_error else d.reply([nid])
        return d.reply()

    return responder


async def connected(dn, d, **kwargs):
    notifier = dn.DBusNotifier()
    original_init = d.FakeBus.__init__

    def init(self, bus_type=None):
        original_init(self, bus_type)
        self.responder = notify_responder(d, **kwargs)

    d.FakeBus.__init__ = init
    try:
        assert await notifier.connect() is True
    finally:
        d.FakeBus.__init__ = original_init
    return notifier


def signal(d, member, body, interface="org.freedesktop.Notifications"):
    return d.Message(message_type=d.MessageType.SIGNAL, interface=interface, member=member, body=body)


async def test_connect_checks_capabilities_and_subscribes(dn, d):
    notifier = await connected(dn, d)
    bus = d.FakeBus.instances[0]
    assert notifier.actions_supported is True
    assert bus.bus_type == d.BusType.SESSION
    members = [m.member for m in bus.calls]
    assert members == ["GetCapabilities", "AddMatch", "AddMatch"]
    rules = [m.body[0] for m in bus.calls if m.member == "AddMatch"]
    assert any("member='ActionInvoked'" in r for r in rules)
    assert any("member='NotificationClosed'" in r for r in rules)
    assert all("sender='org.freedesktop.Notifications'" in r for r in rules)
    assert len(bus.handlers) == 1


async def test_connect_is_idempotent(dn, d):
    notifier = await connected(dn, d)
    assert await notifier.connect() is True
    assert len(d.FakeBus.instances) == 1


async def test_connect_without_actions_capability(dn, d):
    notifier = await connected(dn, d, caps=("body",))
    assert notifier.actions_supported is False


async def test_connect_failure_is_sticky(dn, d):
    d.FakeBus.connect_error = OSError("no session bus")
    notifier = dn.DBusNotifier()
    assert await notifier.connect() is False
    d.FakeBus.connect_error = None
    assert await notifier.connect() is False
    assert len(d.FakeBus.instances) == 1


async def test_connect_error_reply_marks_unavailable(dn, d, monkeypatch):
    original_init = d.FakeBus.__init__

    def init(self, bus_type=None):
        original_init(self, bus_type)
        self.responder = lambda msg: d.error_reply("no daemon")

    monkeypatch.setattr(d.FakeBus, "__init__", init)
    notifier = dn.DBusNotifier()
    assert await notifier.connect() is False
    assert notifier._unavailable is True


async def test_connect_addmatch_error_marks_unavailable(dn, d, monkeypatch):
    original_init = d.FakeBus.__init__

    def init(self, bus_type=None):
        original_init(self, bus_type)
        self.responder = lambda msg: d.error_reply("denied") if msg.member == "AddMatch" else d.reply([["actions"]])

    monkeypatch.setattr(d.FakeBus, "__init__", init)
    notifier = dn.DBusNotifier()
    assert await notifier.connect() is False
    assert notifier._bus is None


async def test_notify_without_connection_returns_none(dn, d):
    assert await dn.DBusNotifier().notify("app", "t", "b") is None


async def test_notify_builds_call_with_flattened_actions_and_image(dn, d):
    notifier = await connected(dn, d, nid=42)
    nid = await notifier.notify("Prism", "Title", "Body", image_path="/img.png",
                                actions=[("0", "Open"), ("1", "Close")], on_action=lambda k: None)
    call = d.FakeBus.instances[0].calls[-1]
    assert nid == 42
    assert call.member == "Notify" and call.signature == "susssasa{sv}i"
    app, replaces, icon, summary, body, actions, hints, timeout = call.body
    assert (app, replaces, icon, summary, body) == ("Prism", 0, "/img.png", "Title", "Body")
    assert actions == ["0", "Open", "1", "Close"]
    assert hints["image-path"].value == "/img.png" and hints["image-path"].signature == "s"
    assert timeout == -1


async def test_notify_without_extras(dn, d):
    notifier = await connected(dn, d)
    await notifier.notify("Prism", "T", "B")
    _, _, icon, _, _, actions, hints, _ = d.FakeBus.instances[0].calls[-1].body
    assert icon == "" and actions == [] and hints == {}


async def test_notify_error_reply_returns_none_and_keeps_bus(dn, d):
    notifier = await connected(dn, d, notify_error="Notify failed")
    assert await notifier.notify("p", "t", "b", actions=[("0", "x")], on_action=lambda k: None) is None
    assert notifier._bus is not None and notifier._pending == {}


async def test_notify_exception_drops_bus_for_reconnect(dn, d):
    notifier = await connected(dn, d)
    d.FakeBus.instances[0].responder = lambda msg: RuntimeError("bus died")
    assert await notifier.notify("p", "t", "b") is None
    assert notifier._bus is None
    assert notifier._unavailable is False


async def test_action_signal_invokes_callback_once(dn, d):
    notifier = await connected(dn, d, nid=5)
    keys = []
    await notifier.notify("p", "t", "b", actions=[("0", "Go")], on_action=keys.append)
    bus = d.FakeBus.instances[0]
    bus.deliver(signal(d, "ActionInvoked", [5, "0"]))
    bus.deliver(signal(d, "ActionInvoked", [5, "0"]))
    assert keys == ["0"]


async def test_action_signal_for_foreign_notification_is_ignored(dn, d):
    notifier = await connected(dn, d, nid=5)
    keys = []
    await notifier.notify("p", "t", "b", actions=[("0", "Go")], on_action=keys.append)
    d.FakeBus.instances[0].deliver(signal(d, "ActionInvoked", [999, "0"]))
    assert keys == [] and 5 in notifier._pending


async def test_closed_signal_drops_pending_callback(dn, d):
    notifier = await connected(dn, d, nid=5)
    keys = []
    await notifier.notify("p", "t", "b", actions=[("0", "Go")], on_action=keys.append)
    bus = d.FakeBus.instances[0]
    bus.deliver(signal(d, "NotificationClosed", [5, 2]))
    bus.deliver(signal(d, "ActionInvoked", [5, "0"]))
    assert keys == [] and notifier._pending == {}


async def test_callback_exception_does_not_break_dispatch(dn, d):
    notifier = await connected(dn, d, nid=5)

    def boom(key):
        raise RuntimeError("bad callback")

    await notifier.notify("p", "t", "b", actions=[("0", "Go")], on_action=boom)
    d.FakeBus.instances[0].deliver(signal(d, "ActionInvoked", [5, "0"]))
    assert notifier._pending == {}


@pytest.mark.parametrize("message", [
    lambda d: d.Message(message_type=d.MessageType.METHOD_RETURN, interface="org.freedesktop.Notifications", member="ActionInvoked", body=[5, "0"]),
    lambda d: signal(d, "ActionInvoked", [5, "0"], interface="org.other.Iface"),
    lambda d: signal(d, "ActionInvoked", [5]),
    lambda d: signal(d, "NotificationClosed", []),
    lambda d: signal(d, "Unknown", [5, "0"]),
])
async def test_malformed_or_foreign_messages_are_ignored(dn, d, message):
    notifier = await connected(dn, d, nid=5)
    keys = []
    await notifier.notify("p", "t", "b", actions=[("0", "Go")], on_action=keys.append)
    d.FakeBus.instances[0].deliver(message(d))
    assert keys == [] and 5 in notifier._pending


async def test_pending_callbacks_are_bounded_oldest_evicted(dn, d):
    notifier = await connected(dn, d)
    counter = iter(range(1, 1000))
    d.FakeBus.instances[0].responder = lambda msg: d.reply([next(counter)]) if msg.member == "Notify" else d.reply()
    for _ in range(dn.DBusNotifier.MAX_PENDING + 5):
        await notifier.notify("p", "t", "b", actions=[("0", "x")], on_action=lambda k: None)
    assert len(notifier._pending) == dn.DBusNotifier.MAX_PENDING
    assert 1 not in notifier._pending and dn.DBusNotifier.MAX_PENDING + 5 in notifier._pending


async def test_notify_without_actions_registers_no_callback(dn, d):
    notifier = await connected(dn, d)
    await notifier.notify("p", "t", "b", on_action=lambda k: None)
    assert notifier._pending == {}


async def test_close_disconnects_and_clears(dn, d):
    notifier = await connected(dn, d, nid=5)
    await notifier.notify("p", "t", "b", actions=[("0", "x")], on_action=lambda k: None)
    bus = d.FakeBus.instances[0]
    await notifier.close()
    assert bus.disconnected and bus.handlers == []
    assert notifier._bus is None and notifier._pending == {}
    await notifier.close()
