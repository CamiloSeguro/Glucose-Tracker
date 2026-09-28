from bisect import bisect_left
from datetime import datetime, timedelta

from src.glucose.settings import GlucoseSettings

KEEP = timedelta(hours=12)


class History:
    """Merges the 15-min graph history from the API with our own 1-min polls."""

    def __init__(self):
        self._points: list[tuple[datetime, float]] = []

    def add(self, at: datetime | None, value: float | None) -> None:
        if at is None or value is None:
            return
        # Every poll resends the whole 12 h graph; skip points we already have
        i = bisect_left(self._points, (at,))
        for t, _ in self._points[max(0, i - 1):i + 1]:
            if abs((at - t).total_seconds()) < 30:
                return
        self._points.insert(i, (at, float(value)))
        cutoff = self._points[-1][0] - KEEP
        while self._points and self._points[0][0] < cutoff:
            self._points.pop(0)

    def extend(self, points: list[tuple[datetime, float]]) -> None:
        for at, value in points:
            self.add(at, value)

    def points(self) -> list[tuple[datetime, float]]:
        return list(self._points)

    def since(self, start: datetime) -> list[tuple[datetime, float]]:
        return [(t, v) for t, v in self._points if t >= start]

    def delta_5min(self, at: datetime, value: float) -> float | None:
        """Change over 5 minutes, like a CGM app shows next to the value.

        Uses the reading closest to 5 min ago; with only 15-min graph points
        available (right after start-up) the change is scaled to a 5-min rate.
        """
        candidates = [
            (t, v) for t, v in self._points
            if timedelta(minutes=3) <= at - t <= timedelta(minutes=20)
        ]
        if not candidates:
            return None
        t, v = min(candidates, key=lambda p: abs((at - p[0]) - timedelta(minutes=5)))
        minutes = (at - t).total_seconds() / 60
        return (value - v) * 5 / minutes


def time_in_range(points: list[tuple[datetime, float]], settings: GlucoseSettings) -> float | None:
    """Time-weighted: 15-min graph points and 1-min polls must not count the same."""
    if len(points) < 2:
        return None
    total = inside = 0.0
    for (t, v), (t_next, _) in zip(points, points[1:]):
        span = min((t_next - t).total_seconds(), 20 * 60)  # don't bridge sensor gaps
        total += span
        if settings.low <= v <= settings.high:
            inside += span
    return inside / total if total else None
