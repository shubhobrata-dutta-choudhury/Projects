"""Weighted Time Interval Merger and Gap Analyzer."""


def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merges overlapping or adjacent closed intervals [start, end] in O(N log N) time."""
    if not intervals:
        return []
    for start, end in intervals:
        if start > end:
            raise ValueError(f"Invalid interval ({start}, {end}): start > end.")
    sorted_intervals = sorted(intervals, key=lambda x: (x[0], x[1]))
    merged: list[tuple[int, int]] = [sorted_intervals[0]]
    for current_start, current_end in sorted_intervals[1:]:
        prev_start, prev_end = merged[-1]
        if current_start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, current_end))
        else:
            merged.append((current_start, current_end))
    return merged


def total_covered_duration(intervals: list[tuple[int, int]]) -> int:
    """Calculates the total continuous duration covered by the merged intervals."""
    merged = merge_intervals(intervals)
    return sum(end - start for start, end in merged)