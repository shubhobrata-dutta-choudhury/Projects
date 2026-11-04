"""Agent-generated unit tests for interval_merger."""
import pytest
from interval_merger import merge_intervals, total_covered_duration


def test_nested_and_negative_intervals():
    data = [(-10, -5), (-7, 0), (0, 4), (10, 12)]
    assert merge_intervals(data) == [(-10, 4), (10, 12)]
    assert total_covered_duration(data) == 14 + 2