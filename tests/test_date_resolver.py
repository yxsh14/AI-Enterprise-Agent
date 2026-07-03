"""Tests for app.utils.date_resolver."""

from app.utils.date_resolver import resolve_date


class TestResolveDate:
    def test_iso_date(self):
        assert resolve_date("meeting on 2026-07-03") == "2026-07-03"

    def test_day_month_year_with_leading_zero(self):
        assert (
            resolve_date("Give the meeting summary for the date 02 July 2026")
            == "2026-07-02"
        )

    def test_day_month_year_without_leading_zero(self):
        assert resolve_date("summary for 2 July 2026") == "2026-07-02"

    def test_day_month_year_with_ordinal(self):
        assert resolve_date("meeting on 2nd July 2026") == "2026-07-02"

    def test_month_day_year(self):
        assert resolve_date("meeting on July 2, 2026") == "2026-07-02"

    def test_month_day_year_with_leading_zero(self):
        assert resolve_date("meeting on July 02 2026") == "2026-07-02"

    def test_numeric_dmy(self):
        assert resolve_date("meeting on 02/07/2026") == "2026-07-02"

    def test_numeric_dmy_dash(self):
        assert resolve_date("meeting on 02-07-2026") == "2026-07-02"

    def test_no_date_returns_none(self):
        assert resolve_date("checkout payments") is None

    def test_weekday_name_is_not_parsed(self):
        assert resolve_date("Summarize the meeting from Wednesday") is None

    def test_last_wednesday_is_not_parsed(self):
        assert resolve_date("What happened last wednesday?") is None

    def test_invalid_date_returns_none(self):
        assert resolve_date("meeting on 31 February 2026") is None
