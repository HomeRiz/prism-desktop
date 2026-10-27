import pytest
from PyQt6.QtWidgets import QApplication, QWidget


class FakeHAClient:
    def __init__(self):
        self.calls = []
        self.states = {}
        self.connected = True

    def get_state(self, entity_id):
        return self.states.get(entity_id)

    def call_service(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return True

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)

        def _noop(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return None
        return _noop


@pytest.fixture
def fake_client():
    return FakeHAClient()


@pytest.fixture
def sample_config():
    return {
        'appearance': {'theme': 'dark', 'rows': 2, 'cols': 4},
        'buttons': [
            {'type': 'switch', 'entity_id': 'light.kitchen', 'label': 'Kitchen', 'row': 0, 'col': 0},
            {'type': 'switch', 'entity_id': 'switch.fan', 'label': 'Fan', 'row': 0, 'col': 1},
            {'type': 'script', 'entity_id': 'script.go', 'label': 'Go', 'row': 1, 'col': 0},
        ],
    }


@pytest.fixture
def host(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


def grab_ok(widget, size=(200, 120)):
    widget.resize(*size)
    pix = widget.grab()
    return (not pix.isNull()) and pix.width() > 0 and pix.height() > 0


@pytest.fixture
def make_button(qtbot):
    from ui.widgets.dashboard_button import DashboardButton

    def _make(config=None, **kw):
        btn = DashboardButton(0, config, **kw)
        qtbot.addWidget(btn)
        return btn
    return _make
