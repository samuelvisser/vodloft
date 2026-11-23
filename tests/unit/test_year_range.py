from backend.utils.helpers import year_range


def test_year_range_is_short_enough_for_a_card():
    assert year_range(2025, 2025) == "2025"
    assert year_range(2016, 2026) == "2016–26"
    assert year_range(2001, 2009) == "2001–09"
    assert year_range(1998, 2026) == "1998–2026"
    assert year_range(None, 2026) == ""
