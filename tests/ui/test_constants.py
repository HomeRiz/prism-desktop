import pytest

from ui import constants as c


def test_calculate_width_matches_documented_formula():
    for cols in (1, 2, 4, 6):
        inner = cols * c.BUTTON_WIDTH + (cols - 1) * c.BUTTON_SPACING
        expected = inner + c.GRID_MARGIN_LEFT + c.GRID_MARGIN_RIGHT + 2 * c.ROOT_MARGIN
        assert c.calculate_width(cols) == expected


def test_calculate_width_default_cols_value():
    assert c.calculate_width(c.DEFAULT_COLS) == 4 * 90 + 3 * 8 + 24 + 20


def test_calculate_width_grows_by_button_plus_spacing_per_column():
    assert c.calculate_width(5) - c.calculate_width(4) == c.BUTTON_WIDTH + c.BUTTON_SPACING


def test_calculate_width_single_column_has_no_spacing():
    assert c.calculate_width(1) == c.BUTTON_WIDTH + 24 + 20


@pytest.mark.parametrize("name", [
    "GLASS_MIN_INTERVAL_MS", "GLASS_MAX_INTERVAL_MS", "ANIM_DURATION_ENTRANCE",
    "BUTTON_HEIGHT", "FOOTER_HEIGHT", "BANNER_HEIGHT", "RESIZE_MARGIN",
])
def test_positive_constants(name):
    assert getattr(c, name) > 0


def test_glass_interval_bounds_are_ordered():
    assert c.GLASS_MIN_INTERVAL_MS < c.GLASS_MAX_INTERVAL_MS
    assert 0 < c.GLASS_WORK_BUDGET <= 1
