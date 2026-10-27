import re

from ui.styles import Typography, Dimensions


def public_attrs(cls):
    return {k: v for k, v in vars(cls).items() if not k.startswith('_')}


def test_font_sizes_are_pixel_values():
    for name, value in public_attrs(Typography).items():
        if name.startswith('SIZE_'):
            assert re.fullmatch(r'\d+px', value), name


def test_font_weights_are_valid_css_weights():
    for name, value in public_attrs(Typography).items():
        if name.startswith('WEIGHT_'):
            assert 100 <= int(value) <= 900 and int(value) % 100 == 0


def test_font_weights_are_ordered():
    t = Typography
    weights = [int(t.WEIGHT_REGULAR), int(t.WEIGHT_MEDIUM), int(t.WEIGHT_SEMIBOLD), int(t.WEIGHT_BOLD)]
    assert weights == sorted(weights)


def test_font_families_are_non_empty_strings():
    assert Typography.FONT_FAMILY_MAIN
    assert "sans-serif" in Typography.FONT_FAMILY_UI


def test_dimensions_are_pixel_values_and_ordered():
    d = Dimensions
    for name, value in public_attrs(d).items():
        assert re.fullmatch(r'\d+px', value), name
    assert int(d.RADIUS_SMALL[:-2]) < int(d.RADIUS_MEDIUM[:-2]) < int(d.RADIUS_XLARGE[:-2])
    assert int(d.PADDING_SMALL[:-2]) < int(d.PADDING_MEDIUM[:-2]) < int(d.PADDING_LARGE[:-2])


def test_font_sizes_can_be_embedded_in_stylesheet(qtbot):
    from PyQt6.QtWidgets import QLabel
    label = QLabel("x")
    qtbot.addWidget(label)
    label.setStyleSheet(f"font-size: {Typography.SIZE_BODY}; border-radius: {Dimensions.RADIUS_MEDIUM};")
    assert label.grab().width() > 0
