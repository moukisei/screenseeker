"""Jinja filters that format model values for the templates."""

import pytest

from screenseeker.web.rendering import _runtime


class TestRuntimeFilter:
    @pytest.mark.parametrize(
        "minutes, expected",
        [
            (125, "2h 5m"),
            (120, "2h"),
            (45, "45m"),
            (60, "1h"),
            (61, "1h 1m"),
        ],
    )
    def test_formats_minutes_as_hours_and_minutes(self, minutes, expected):
        assert _runtime(minutes) == expected

    @pytest.mark.parametrize("value", [None, 0])
    def test_an_unknown_or_zero_runtime_is_an_em_dash(self, value):
        assert _runtime(value) == "—"
