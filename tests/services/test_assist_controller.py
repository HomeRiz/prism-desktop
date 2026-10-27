import asyncio
from unittest import mock

import pytest
from PyQt6.QtMultimedia import QAudio

from services import assist_controller as ac


class Sig:
    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def disconnect(self, fn):
        self.slots.remove(fn)


class FakeIO:
    def __init__(self):
        self.readyRead = Sig()
        self.buffer = b""

    def readAll(self):
        data, self.buffer = self.buffer, b""
        return data


class FakeSource:
    instances = []
    error_code = QAudio.Error.NoError

    def __init__(self, device, fmt):
        self.io = FakeIO()
        self.fmt = fmt
        self.stopped = self.deleted = False
        FakeSource.instances.append(self)

    def start(self):
        return self.io

    def error(self):
        return FakeSource.error_code

    def format(self):
        return self.fmt

    def stop(self):
        self.stopped = True

    def deleteLater(self):
        self.deleted = True


class FakeDevice:
    def __init__(self, ident=b"mic1", null=False):
        self._id, self._null = ident, null

    def id(self):
        return self._id

    def isNull(self):
        return self._null

    def description(self):
        return "Fake mic"

    def isFormatSupported(self, fmt):
        return True


class FakeDevices:
    inputs = []
    default = FakeDevice()

    @staticmethod
    def audioInputs():
        return FakeDevices.inputs

    @staticmethod
    def defaultAudioInput():
        return FakeDevices.default

    @staticmethod
    def audioOutputs():
        return []


class FakePlayer:
    instances = []

    def __init__(self):
        self.played = self.stopped = self.deleted = False
        FakePlayer.instances.append(self)

    def setAudioOutput(self, out):
        self.out = out

    def setSourceDevice(self, dev):
        self.dev = dev

    def play(self):
        self.played = True

    def stop(self):
        self.stopped = True

    def deleteLater(self):
        self.deleted = True


class FakeOutput:
    def __init__(self, *a):
        pass

    def deleteLater(self):
        pass


class FakeWS:
    def __init__(self, events=(), process_result=None, process_error=None):
        self.events = list(events)
        self.process_result = process_result
        self.process_error = process_error
        self.sent = []
        self.ended = []
        self.pipeline_args = None
        self.hold = None

    async def conversation_process(self, text, conversation_id=None):
        self.process_args = (text, conversation_id)
        if self.process_error:
            raise self.process_error
        return self.process_result

    async def run_assist_pipeline(self, conversation_id=None, sample_rate=16000):
        self.pipeline_args = (conversation_id, sample_rate)
        for event in self.events:
            if event == "hold":
                await self.hold.wait()
                continue
            if isinstance(event, Exception):
                raise event
            yield event

    async def send_stt_audio(self, handler_id, chunk):
        self.sent.append((handler_id, chunk))

    async def end_stt_audio(self, handler_id):
        self.ended.append(handler_id)


@pytest.fixture(autouse=True)
def fake_audio(monkeypatch, qapp):
    FakeSource.instances, FakeSource.error_code = [], QAudio.Error.NoError
    FakePlayer.instances = []
    FakeDevices.inputs, FakeDevices.default = [], FakeDevice()
    monkeypatch.setattr(ac, "QAudioSource", FakeSource)
    monkeypatch.setattr(ac, "QMediaDevices", FakeDevices)
    monkeypatch.setattr(ac, "QMediaPlayer", FakePlayer)
    monkeypatch.setattr(ac, "QAudioOutput", FakeOutput)


def make(ws, config=None, client=None):
    controller = ac.AssistController(lambda: ws, client or mock.Mock(), lambda: config or {})
    log = {}
    for name in ("listening_started", "listening_stopped", "heard", "thinking", "reply_ready", "error"):
        log[name] = []
        getattr(controller, name).connect(lambda *a, _n=name: log[_n].append(a[0] if a else None))
    controller.log = log
    return controller


async def settle(controller):
    task = controller._pipeline_task
    if task:
        await asyncio.wait_for(task, 3)
    await asyncio.sleep(0.02)


def test_find_audio_device_matches_by_id():
    devices = [FakeDevice(b"a"), FakeDevice(b"b")]
    assert ac._find_audio_device(devices, "b") is devices[1]
    assert ac._find_audio_device(devices, "zzz") is None
    assert ac._find_audio_device(devices, "") is None


async def test_submit_text_blank_is_ignored():
    controller = make(FakeWS())
    controller.submit_text("   ")
    assert controller.log["thinking"] == []


async def test_submit_text_without_websocket_reports_error():
    controller = ac.AssistController(lambda: None, mock.Mock())
    errors = []
    controller.error.connect(errors.append)
    controller.submit_text("hi")
    assert errors == ["Not connected to Home Assistant"]


async def test_submit_text_replies_and_tracks_conversation():
    result = {"conversation_id": "c1", "response": {"speech": {"plain": {"speech": "Lights on"}}}}
    ws = FakeWS(process_result=result)
    controller = make(ws)
    controller.submit_text("  turn on lights ")
    await asyncio.sleep(0.05)
    assert ws.process_args == ("turn on lights", None)
    assert controller.log["thinking"] == [None] and controller.log["reply_ready"] == ["Lights on"]
    assert controller.conversation_id == "c1"
    ws.process_result = {"response": {}}
    controller.submit_text("again")
    await asyncio.sleep(0.05)
    assert ws.process_args == ("again", "c1")
    assert controller.log["reply_ready"][-1] == "Done." and controller.conversation_id == "c1"
    controller.reset_conversation()
    assert controller.conversation_id is None


@pytest.mark.parametrize("exc,expected", [(RuntimeError("boom"), "boom"), (RuntimeError(), "Assist request failed")])
async def test_submit_text_failure_emits_error(exc, expected):
    controller = make(FakeWS(process_error=exc))
    controller.submit_text("hi")
    await asyncio.sleep(0.05)
    assert controller.log["error"] == [expected] and controller.log["reply_ready"] == []


async def test_start_voice_without_websocket_or_microphone():
    controller = ac.AssistController(lambda: None, mock.Mock())
    errors = []
    controller.error.connect(errors.append)
    controller.start_voice()
    FakeDevices.default = FakeDevice(null=True)
    controller2 = make(FakeWS())
    controller2.start_voice()
    assert errors == ["Not connected to Home Assistant"]
    assert controller2.log["error"] == ["No microphone found"] and not controller2._recording


async def test_start_voice_microphone_open_failure_resets_state():
    FakeSource.error_code = QAudio.Error.OpenError
    controller = make(FakeWS())
    controller.start_voice()
    assert controller.log["error"][0].startswith("Could not access microphone")
    assert not controller._recording and controller._audio_source is None
    assert FakeSource.instances[0].deleted and controller._pipeline_task is None


async def test_start_voice_uses_configured_microphone():
    chosen = FakeDevice(b"usb")
    FakeDevices.inputs = [FakeDevice(b"other"), chosen]
    seen = []
    original = FakeSource.__init__
    FakeSource.__init__ = lambda self, device, fmt: (seen.append(device), original(self, device, fmt))[1]
    try:
        controller = make(FakeWS(), config={"assist": {"mic_device_id": "usb"}})
        controller.start_voice()
        controller.cancel()
    finally:
        FakeSource.__init__ = original
    assert seen == [chosen]


async def test_full_voice_session_streams_audio_and_emits_results():
    events = [
        {"type": "run-start", "data": {"runner_data": {"stt_binary_handler_id": 3}}},
        {"type": "stt-start", "data": {}},
        "hold",
        {"type": "stt-end", "data": {"stt_output": {"text": "lights on"}}},
        {"type": "intent-start", "data": {}},
        {"type": "intent-end", "data": {"intent_output": {"conversation_id": "c9", "response": {"speech": {"plain": {"speech": "Done it"}}}}}},
        {"type": "run-end", "data": {}},
    ]
    ws = FakeWS(events)
    ws.hold = asyncio.Event()
    controller = make(ws)
    controller.start_voice()
    assert controller.log["listening_started"] == [None] and controller._recording
    source = FakeSource.instances[0]
    source.io.buffer = b"\x01\x02"
    source.io.readyRead.slots[0]()
    await asyncio.sleep(0.05)
    ws.hold.set()
    await settle(controller)
    assert ws.pipeline_args == (None, 16000)
    assert ws.sent == [(3, b"\x01\x02")]
    assert controller.log["heard"] == ["lights on"] and controller.log["thinking"] == [None]
    assert controller.log["reply_ready"] == ["Done it"] and controller.conversation_id == "c9"
    assert controller.log["listening_stopped"] == [None] and not controller._recording
    assert source.stopped and source.deleted


async def test_pipeline_error_event_is_reported_and_recording_stopped():
    ws = FakeWS([{"type": "error", "data": {"message": "stt-no-text-recognized"}}, {"type": "run-end"}])
    controller = make(ws)
    controller.start_voice()
    await settle(controller)
    assert controller.log["error"] == ["stt-no-text-recognized"]
    assert not controller._recording and controller.log["listening_stopped"] == [None]


async def test_pipeline_exception_is_reported():
    controller = make(FakeWS([RuntimeError("socket closed")]))
    controller.start_voice()
    await settle(controller)
    assert controller.log["error"] == ["socket closed"] and not controller._recording


async def test_tts_end_schedules_playback(monkeypatch):
    played = []

    async def play(self, url):
        played.append(url)

    monkeypatch.setattr(ac.AssistController, "_play_tts", play)
    ws = FakeWS([{"type": "tts-end", "data": {"tts_output": {"url": "/api/tts/x.mp3"}}}, {"type": "run-end"}])
    controller = make(ws)
    controller.start_voice()
    await settle(controller)
    assert played == ["/api/tts/x.mp3"]


async def test_second_voice_request_rejected_while_pipeline_running():
    ws = FakeWS(["hold"])
    ws.hold = asyncio.Event()
    controller = make(ws)
    controller.start_voice()
    controller._stop_recording()
    controller.start_voice()
    assert controller.log["error"] == ["Assist is still finishing the previous request"]
    ws.hold.set()
    await settle(controller)


async def test_stop_voice_ends_stream_and_queues_sentinel():
    controller = make(FakeWS(["hold"]))
    controller._get_websocket().hold = asyncio.Event()
    controller.start_voice()
    controller.stop_voice()
    assert controller._audio_queue.get_nowait() is None
    assert controller.log["listening_stopped"] == [None]
    controller.stop_voice()
    assert controller.log["listening_stopped"] == [None]
    controller.cancel()


async def test_cancel_aborts_pipeline_and_playback():
    ws = FakeWS(["hold"])
    ws.hold = asyncio.Event()
    controller = make(ws)
    controller.start_voice()
    task = controller._pipeline_task
    controller._media_player = player = FakePlayer()
    controller.cancel()
    await asyncio.sleep(0.02)
    assert task.cancelled() and controller._pipeline_task is None
    assert not controller._recording and player.stopped and controller._media_player is None


async def test_play_tts_without_audio_does_nothing():
    client = mock.Mock()
    client.fetch_media = mock.AsyncMock(return_value=None)
    controller = make(FakeWS(), client=client)
    await controller._play_tts("/api/tts/x")
    client.fetch_media.assert_awaited_once_with("/api/tts/x", kind="TTS audio")
    assert FakePlayer.instances == []


async def test_play_tts_replaces_previous_player():
    client = mock.Mock()
    client.fetch_media = mock.AsyncMock(return_value=b"mp3data")
    controller = make(FakeWS(), client=client)
    await controller._play_tts("/u1")
    first = FakePlayer.instances[0]
    assert first.played and controller._tts_buffer.data() == b"mp3data"
    await controller._play_tts("/u2")
    assert first.stopped and first.deleted and len(FakePlayer.instances) == 2
    controller._stop_tts_playback()
    assert controller._media_player is None and controller._tts_buffer is None


async def test_stream_audio_sends_chunks_until_sentinel_then_ends():
    ws = FakeWS()
    controller = make(ws)
    controller._audio_queue = asyncio.Queue()
    for item in (b"a", b"b", None):
        controller._audio_queue.put_nowait(item)
    await controller._stream_audio(ws, 7)
    assert ws.sent == [(7, b"a"), (7, b"b")] and ws.ended == [7]
