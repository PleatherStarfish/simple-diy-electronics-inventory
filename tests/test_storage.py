from eurorack_inventory.domain.storage import (
    GridRegion,
    grid_region_to_label,
    index_to_row_label,
    parse_grid_region,
    region_within_bounds,
    regions_overlap,
    row_label_to_index,
)


def test_row_label_round_trip() -> None:
    assert row_label_to_index("A") == 0
    assert row_label_to_index("Z") == 25
    assert row_label_to_index("AA") == 26
    assert index_to_row_label(0) == "A"
    assert index_to_row_label(25) == "Z"
    assert index_to_row_label(26) == "AA"


def test_parse_single_cell_region() -> None:
    region = parse_grid_region("B3")
    assert region == GridRegion(row_start=1, col_start=3, row_end=1, col_end=3)
    assert grid_region_to_label(region) == "B3"


def test_parse_merged_region() -> None:
    region = parse_grid_region("A0-B2")
    assert region == GridRegion(row_start=0, col_start=0, row_end=1, col_end=2)
    assert grid_region_to_label(region) == "A0-B2"


def test_overlap_detection() -> None:
    a = parse_grid_region("A0-A1")
    b = parse_grid_region("A1-B1")
    c = parse_grid_region("C0-C1")
    assert regions_overlap(a, b) is True
    assert regions_overlap(a, c) is False


def test_region_bounds() -> None:
    assert region_within_bounds(parse_grid_region("A0-B2"), rows=4, cols=4) is True
    assert region_within_bounds(parse_grid_region("D0"), rows=3, cols=4) is False
