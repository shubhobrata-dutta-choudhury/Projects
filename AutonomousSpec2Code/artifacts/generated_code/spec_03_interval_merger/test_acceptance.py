"""Auto-generated acceptance test suite for spec_03_interval_merger: Weighted Time Interval Merger & Gap Analyzer."""
import pytest
import math
import time
from interval_merger import *


# [test_overlapping_and_adjacent_merge] Merges unsorted overlapping and adjacent intervals properly.
def test_overlapping_and_adjacent_merge():
    raw = [(10, 15), (1, 3), (3, 6), (8, 12)]
    assert merge_intervals(raw) == [(1, 6), (8, 15)]
    assert total_covered_duration(raw) == (6 - 1) + (15 - 8)


# [test_empty_and_zero_length_intervals] Handles empty lists and point intervals (start == end).
def test_empty_and_zero_length_intervals():
    assert merge_intervals([]) == []
    assert total_covered_duration([]) == 0
    assert merge_intervals([(4, 4), (4, 7)]) == [(4, 7)]
    assert total_covered_duration([(4, 4)]) == 0


# [test_invalid_interval_raises] Raises ValueError when start > end.
def test_invalid_interval_raises():
    with pytest.raises(ValueError):
        merge_intervals([(5, 2)])