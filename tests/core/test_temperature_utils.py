import pytest

from core import temperature_utils as tu


@pytest.mark.parametrize("raw,expected", [
    ("C", "C"), ("c", "C"), ("°C", "C"), (" celsius ", "C"), ("CELSIUS", "C"),
    ("F", "F"), ("f", "F"), ("°F", "F"), ("Fahrenheit", "F"),
    ("K", None), ("", None), (None, None), ("warm", None), (5, None),
])
def test_normalize_temperature_unit(raw, expected):
    assert tu.normalize_temperature_unit(raw) == expected


@pytest.mark.parametrize("pref,fallback,expected", [
    ("celsius", None, "C"),
    ("Fahrenheit", None, "F"),
    ("°f", None, "F"),
    ("system", "°C", "C"),
    ("system", None, None),
    (None, "F", "F"),
    ("", "bogus", None),
])
def test_preference_to_unit(pref, fallback, expected):
    assert tu.preference_to_unit(pref, fallback) == expected


@pytest.mark.parametrize("unit,suffix", [("C", "°C"), ("f", "°F"), (None, "°"), ("K", "°")])
def test_unit_suffix(unit, suffix):
    assert tu.unit_suffix(unit) == suffix


def test_is_temperature_unit():
    assert tu.is_temperature_unit("°C")
    assert not tu.is_temperature_unit("%")


@pytest.mark.parametrize("attrs,expected", [
    (None, False),
    ({}, False),
    ({"device_class": "Temperature"}, True),
    ({"unit_of_measurement": "°F"}, True),
    ({"temperature_unit": "C"}, True),
    ({"device_class": "humidity", "unit_of_measurement": "%"}, False),
])
def test_is_temperature_entity(attrs, expected):
    assert tu.is_temperature_entity(attrs) is expected


@pytest.mark.parametrize("value,src,dst,expected", [
    (0, "C", "F", 32.0),
    (100, "C", "F", 212.0),
    (32, "F", "C", 0.0),
    (212, "F", "C", 100.0),
    (-40, "C", "F", -40.0),
    ("21.5", "C", "C", 21.5),
    (20, "C", "K", 20.0),
    (20, None, "F", 20.0),
])
def test_convert_temperature(value, src, dst, expected):
    assert tu.convert_temperature(value, src, dst) == pytest.approx(expected)


@pytest.mark.parametrize("value", [None, "", "--", "abc", [], {}])
def test_convert_temperature_invalid_values_return_none(value):
    assert tu.convert_temperature(value, "C", "F") is None


@pytest.mark.parametrize("value,src,dst,expected", [
    (10, "C", "F", 18.0),
    (18, "F", "C", 10.0),
    (5, "C", "C", 5.0),
    (5, "C", None, 5.0),
])
def test_convert_temperature_delta_has_no_offset(value, src, dst, expected):
    assert tu.convert_temperature_delta(value, src, dst) == pytest.approx(expected)


@pytest.mark.parametrize("value", [None, "", "--", "x"])
def test_convert_temperature_delta_invalid_returns_none(value):
    assert tu.convert_temperature_delta(value, "C", "F") is None


@pytest.mark.parametrize("args,kwargs,expected", [
    ((20, "C"), {}, "20°C"),
    ((20.05, "C"), {}, "20.1°C"),
    ((20.04, "C"), {}, "20°C"),
    ((20.5, "C"), {"precision": 0}, "20°C"),
    ((0, "C", "fahrenheit"), {}, "32°F"),
    ((68, "F", "celsius"), {}, "20°C"),
    ((-0.04, "C"), {}, "0°C"),
    ((100, "C"), {"precision": 2}, "100°C"),
    ((20.25, "C"), {"precision": 2}, "20.25°C"),
    ((None, "C"), {}, "--°C"),
    (("--", "F"), {}, "--°F"),
    ((None, None), {}, "--"),
    ((None, None), {"fallback": "n/a"}, "n/a"),
    ((21, None), {}, "--"),
])
def test_format_temperature(args, kwargs, expected):
    assert tu.format_temperature(*args, **kwargs) == expected
