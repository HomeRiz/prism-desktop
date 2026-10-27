import pytest

from ui.grid_layout_engine import GridLayoutEngine, plan_move


class FakeButton:
    def __init__(self, config=None, span_x=1, span_y=1, visible=True):
        self.config = config
        if span_x is not None:
            self.span_x = span_x
        if span_y is not None:
            self.span_y = span_y
        self._visible = visible

    def isVisible(self):
        return self._visible


def real(row, col, span_x=1, span_y=1, entity="light.x"):
    return FakeButton({'entity_id': entity, 'row': row, 'col': col}, span_x, span_y)


def empty():
    return FakeButton({})


def cells(placement):
    _, r, c, sy, sx = placement
    return {(r + dy, c + dx) for dy in range(sy) for dx in range(sx)}


def by_button(placements):
    return {id(p[0]): p for p in placements}


def test_single_button_placed_at_its_coordinates():
    b = real(1, 2)
    out = GridLayoutEngine(4).calculate_layout([b], 3)
    assert (b, 1, 2, 1, 1) in out


def test_empty_grid_filled_with_empty_buttons_in_reading_order():
    empties = [empty() for _ in range(6)]
    out = GridLayoutEngine(3).calculate_layout(empties, 2)
    assert [(r, c) for _, r, c, _, _ in out] == [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]


def test_fewer_empty_buttons_than_cells_leaves_holes():
    out = GridLayoutEngine(3).calculate_layout([empty()], 2)
    assert len(out) == 1


def test_surplus_empty_buttons_are_dropped():
    out = GridLayoutEngine(2).calculate_layout([empty() for _ in range(9)], 1)
    assert len(out) == 2


def test_empty_buttons_skip_cells_occupied_by_real_ones():
    real_b = real(0, 0, span_x=2)
    out = GridLayoutEngine(3).calculate_layout([real_b, empty(), empty()], 1)
    positions = {(r, c) for _, r, c, _, _ in out}
    assert positions == {(0, 0), (0, 2)}


def test_spans_are_reported_as_span_y_then_span_x():
    b = real(0, 0, span_x=2, span_y=3)
    out = GridLayoutEngine(4).calculate_layout([b], 3)
    assert out == [(b, 0, 0, 3, 2)]


def test_pin_window_counts_as_configured_without_entity():
    b = FakeButton({'type': 'pin_window', 'row': 0, 'col': 1})
    out = GridLayoutEngine(3).calculate_layout([b], 1)
    assert (b, 0, 1, 1, 1) in out


def test_button_without_config_treated_as_empty():
    b = FakeButton(None)
    out = GridLayoutEngine(2).calculate_layout([b], 1)
    assert out[0][0] is b


def test_config_without_entity_or_pin_window_is_empty_placeholder():
    b = FakeButton({'type': 'switch', 'row': 1, 'col': 1})
    out = GridLayoutEngine(2).calculate_layout([b], 2)
    assert (b, 0, 0, 1, 1) in out


def test_missing_row_col_default_to_origin():
    b = FakeButton({'entity_id': 'light.a'})
    out = GridLayoutEngine(2).calculate_layout([b], 2)
    assert (b, 0, 0, 1, 1) in out


def test_missing_span_attributes_default_to_one():
    b = FakeButton({'entity_id': 'light.a', 'row': 0, 'col': 0}, span_x=None, span_y=None)
    out = GridLayoutEngine(2).calculate_layout([b], 2)
    assert (b, 0, 0, 1, 1) in out


def test_collision_second_button_is_dropped_and_cells_forbidden():
    a = real(0, 0, span_x=2)
    b = real(0, 1)
    eng = GridLayoutEngine(3)
    out = eng.calculate_layout([a, b], 1)
    placed = [p[0] for p in out]
    assert a in placed and b not in placed
    assert eng.get_forbidden_cells() == set()


def test_collision_with_free_cells_marks_only_unoccupied_cells_forbidden():
    a = real(0, 0)
    b = real(0, 0, span_x=2)
    eng = GridLayoutEngine(3)
    out = eng.calculate_layout([a, b], 1)
    assert b not in [p[0] for p in out]
    assert eng.get_forbidden_cells() == {(0, 1)}


def test_deterministic_priority_sorted_by_row_then_col():
    first = real(0, 0)
    dup = real(0, 0, entity="light.dup")
    for order in ([first, dup], [dup, first]):
        out = GridLayoutEngine(2).calculate_layout(order, 1)
        placed = [p[0] for p in out]
        assert len(placed) == 1


def test_button_exceeding_columns_is_hidden_and_visible_part_forbidden():
    b = real(0, 2, span_x=3)
    eng = GridLayoutEngine(4)
    out = eng.calculate_layout([b], 2)
    assert b not in [p[0] for p in out]
    assert eng.get_forbidden_cells() == {(0, 2), (0, 3)}


def test_button_exceeding_rows_is_hidden():
    b = real(1, 0, span_y=2)
    eng = GridLayoutEngine(2)
    out = eng.calculate_layout([b, empty(), empty(), empty(), empty()], 2)
    assert b not in [p[0] for p in out]
    assert eng.get_forbidden_cells() == {(1, 0)}


def test_button_fully_outside_grid_has_no_forbidden_cells():
    b = real(9, 9)
    eng = GridLayoutEngine(4)
    out = eng.calculate_layout([b], 2)
    assert out == []
    assert eng.get_forbidden_cells() == set()


def test_forbidden_cells_reset_between_calls():
    eng = GridLayoutEngine(2)
    eng.calculate_layout([real(0, 1, span_x=2)], 1)
    assert eng.get_forbidden_cells()
    eng.calculate_layout([real(0, 0)], 1)
    assert eng.get_forbidden_cells() == set()


def test_forbidden_cells_before_any_layout_is_empty():
    assert GridLayoutEngine(4).get_forbidden_cells() == set()


def test_hidden_button_cells_get_filled_by_empty_buttons():
    b = real(0, 1, span_x=2)
    e = [empty(), empty()]
    out = GridLayoutEngine(2).calculate_layout([b] + e, 1)
    assert sorted((r, c) for _, r, c, _, _ in out) == [(0, 0), (0, 1)]


def test_placements_never_overlap_and_stay_in_grid():
    buttons = [real(0, 0, 2, 2), real(0, 2), real(1, 2), real(2, 0, 3, 1), real(1, 1), empty(), empty()]
    rows, cols = 4, 4
    out = GridLayoutEngine(cols).calculate_layout(buttons, rows)
    seen = set()
    for p in out:
        cs = cells(p)
        assert not (cs & seen)
        assert all(0 <= r < rows and 0 <= c < cols for r, c in cs)
        seen |= cs


def test_zero_rows_yields_nothing():
    assert GridLayoutEngine(4).calculate_layout([real(0, 0), empty()], 0) == []


def test_empty_button_list_yields_nothing():
    assert GridLayoutEngine(4).calculate_layout([], 3) == []


def test_resize_grid_hides_then_reveals_button_with_stable_coords():
    b = real(2, 3)
    eng = GridLayoutEngine(4)
    assert eng.calculate_layout([b], 2) == []
    assert eng.calculate_layout([b], 3) == [(b, 2, 3, 1, 1)]


def test_shrinking_columns_hides_wide_button():
    b = real(0, 0, span_x=3)
    assert GridLayoutEngine(2).calculate_layout([b], 1) == []
    assert GridLayoutEngine(3).calculate_layout([b], 1) == [(b, 0, 0, 1, 3)]


def test_find_first_empty_slot_on_empty_grid():
    assert GridLayoutEngine(3).find_first_empty_slot([], 2) == (0, 0)


def test_find_first_empty_slot_skips_occupied():
    eng = GridLayoutEngine(3)
    assert eng.find_first_empty_slot([real(0, 0), real(0, 1)], 2) == (0, 2)


def test_find_first_empty_slot_respects_span():
    eng = GridLayoutEngine(3)
    btns = [real(0, 1)]
    assert eng.find_first_empty_slot(btns, 2, span_x=2) == (1, 0)


def test_find_first_empty_slot_full_grid_returns_sentinel():
    eng = GridLayoutEngine(2)
    btns = [real(0, 0), real(0, 1)]
    assert eng.find_first_empty_slot(btns, 1) == (-1, -1)


def test_find_first_empty_slot_span_too_wide_returns_sentinel():
    assert GridLayoutEngine(2).find_first_empty_slot([], 3, span_x=3) == (-1, -1)


def test_find_first_empty_slot_ignores_hidden_and_unconfigured_buttons():
    hidden = FakeButton({'entity_id': 'a', 'row': 0, 'col': 0}, visible=False)
    bare = FakeButton(None)
    assert GridLayoutEngine(2).find_first_empty_slot([hidden, bare], 1) == (0, 0)


def test_find_first_empty_slot_empty_dict_config_is_falsy_and_ignored():
    placeholder = FakeButton({})
    assert GridLayoutEngine(2).find_first_empty_slot([placeholder], 1) == (0, 0)


def test_relocations_empty_when_no_overlap():
    eng = GridLayoutEngine(4)
    a, b = real(0, 0), real(0, 3)
    assert eng.find_relocations(a, 2, 1, [a, b], 2) == []


def test_relocations_for_unconfigured_button_is_empty():
    eng = GridLayoutEngine(4)
    assert eng.find_relocations(FakeButton(None), 2, 2, [], 2) == []


def test_relocation_moves_displaced_to_first_free_cell():
    eng = GridLayoutEngine(3)
    a, b = real(0, 0), real(0, 1)
    out = eng.find_relocations(a, 2, 1, [a, b], 2)
    assert out == [(b, 0, 2)]


def test_relocation_blocked_when_no_room():
    eng = GridLayoutEngine(2)
    a, b = real(0, 0), real(0, 1)
    assert eng.find_relocations(a, 2, 1, [a, b], 1) is None


def test_relocation_multiple_displaced_get_distinct_cells():
    eng = GridLayoutEngine(3)
    a, b, c = real(0, 0), real(0, 1), real(1, 0)
    out = eng.find_relocations(a, 2, 2, [a, b, c], 3)
    targets = {(r, cc) for _, r, cc in out}
    assert len(out) == 2
    assert len(targets) == 2
    assert not (targets & {(0, 0), (0, 1), (1, 0), (1, 1)})


def test_relocation_respects_displaced_spans():
    eng = GridLayoutEngine(3)
    a, b = real(0, 0), real(0, 1, span_x=2)
    out = eng.find_relocations(a, 2, 1, [a, b], 2)
    assert out == [(b, 1, 0)]


def test_relocation_ignores_empty_placeholders():
    eng = GridLayoutEngine(3)
    a, ph = real(0, 0), FakeButton({'row': 0, 'col': 1})
    assert eng.find_relocations(a, 2, 1, [a, ph], 1) == []


def test_relocation_does_not_use_cells_of_untouched_buttons():
    eng = GridLayoutEngine(3)
    a, b, keep = real(0, 0), real(0, 1), real(0, 2)
    out = eng.find_relocations(a, 2, 1, [a, b, keep], 2)
    assert out == [(b, 1, 0)]


def test_relocation_falls_back_to_config_span_when_attribute_missing():
    eng = GridLayoutEngine(3)
    a = real(0, 0)
    b = FakeButton({'entity_id': 'x', 'row': 0, 'col': 1, 'span_x': 2}, span_x=None, span_y=None)
    out = eng.find_relocations(a, 2, 1, [a, b], 2)
    assert out == [(b, 1, 0)]


def cfg(row, col, sx=1, sy=1, entity='light.x'):
    return {'entity_id': entity, 'row': row, 'col': col, 'span_x': sx, 'span_y': sy}


def test_plan_move_to_free_cell():
    a = cfg(0, 0)
    assert plan_move([a], a, None, 1, 1, 3, 3) == {id(a): (1, 1)}


def test_plan_move_swaps_with_target_origins():
    a, b = cfg(0, 0), cfg(1, 1)
    out = plan_move([a, b], a, b, 1, 1, 3, 3)
    assert out == {id(a): (1, 1), id(b): (0, 0)}


@pytest.mark.xfail(strict=True, reason="plan_move checks the source twice when target is source, so dropping a tile on itself returns None instead of a no-op move")
def test_plan_move_onto_itself_is_just_source_move():
    a = cfg(0, 0)
    assert plan_move([a], a, a, 0, 0, 3, 3) == {id(a): (0, 0)}


def test_plan_move_blocked_by_other_button():
    a, b, c = cfg(0, 0), cfg(0, 1), cfg(2, 2)
    assert plan_move([a, b, c], a, None, 0, 1, 3, 3) is None


def test_plan_move_wide_tile_cannot_leave_grid():
    a = cfg(0, 0, sx=2)
    assert plan_move([a], a, None, 0, 2, 3, 3) is None
    assert plan_move([a], a, None, 0, 1, 3, 3) == {id(a): (0, 1)}


def test_plan_move_tall_tile_cannot_leave_grid():
    a = cfg(0, 0, sy=2)
    assert plan_move([a], a, None, 2, 0, 3, 3) is None


def test_plan_move_wide_tile_cannot_land_on_neighbour():
    a, b = cfg(0, 0, sx=2), cfg(0, 3)
    assert plan_move([a, b], a, None, 0, 2, 4, 2) is None


def test_plan_move_swap_with_mismatched_spans_fails_when_overlapping():
    a, b = cfg(0, 0, sx=2), cfg(0, 2)
    assert plan_move([a, b], a, b, 0, 2, 3, 2) is None


def test_plan_move_swap_with_mismatched_spans_succeeds_when_room():
    a, b = cfg(0, 0, sx=2), cfg(1, 0)
    out = plan_move([a, b], a, b, 1, 0, 3, 3)
    assert out == {id(a): (1, 0), id(b): (0, 0)}


def test_plan_move_ignores_placeholder_configs_when_checking_collisions():
    a = cfg(0, 0)
    placeholder = {'row': 1, 'col': 1}
    assert plan_move([a, placeholder], a, None, 1, 1, 3, 3) == {id(a): (1, 1)}


def test_plan_move_pin_window_blocks_target():
    a = cfg(0, 0)
    pin = {'type': 'pin_window', 'row': 1, 'col': 1}
    assert plan_move([a, pin], a, None, 1, 1, 3, 3) is None


@pytest.mark.parametrize("cols,rows,r,c,ok", [
    (1, 1, 0, 0, True), (1, 1, 1, 0, False), (2, 2, 1, 1, True), (2, 2, 2, 2, False),
    (3, 1, 0, 2, True), (3, 1, 0, 3, False),
])
def test_plan_move_bounds(cols, rows, r, c, ok):
    a = cfg(0, 0)
    assert (plan_move([a], a, None, r, c, cols, rows) is not None) is ok
