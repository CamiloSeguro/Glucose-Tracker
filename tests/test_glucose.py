import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from src.glucose import render
from src.glucose.alerts import AlertManager, classify
from src.glucose.history import History, time_in_range
from src.glucose.settings import GlucoseSettings

NOW = datetime(2026, 9, 27, 22, 0, tzinfo=timezone.utc)


def ago(minutes: float) -> datetime:
    return NOW - timedelta(minutes=minutes)


class SettingsTest(unittest.TestCase):
    def test_parses_strings_and_ignores_garbage(self):
        s = GlucoseSettings.from_global({"unit": "mmol", "low": "65", "alerts": "false", "email": "x"})
        self.assertEqual((s.unit, s.low, s.alerts), ("mmol", 65, False))

    def test_inconsistent_thresholds_fall_back_to_defaults(self):
        s = GlucoseSettings.from_global({"low": 200, "high": 100})
        self.assertEqual((s.low, s.high), (70, 180))

    def test_formatting(self):
        mg, mm = GlucoseSettings(), GlucoseSettings(unit="mmol")
        self.assertEqual(mg.format_value(123.4), "123")
        self.assertEqual(mm.format_value(180), "10.0")
        self.assertEqual(mg.format_delta(6.4), "+6")
        self.assertEqual(mg.format_delta(0.2), "±0")
        self.assertEqual(mm.format_delta(-9), "-0.5")
        self.assertEqual(mg.format_delta(None), "")


class HistoryTest(unittest.TestCase):
    def test_resending_graph_does_not_duplicate(self):
        h = History()
        graph = [(ago(m), 100 + m) for m in range(0, 180, 15)]
        h.extend(graph)
        h.extend(graph)
        h.add(ago(0) + timedelta(seconds=10), 100)
        self.assertEqual(len(h.points()), len(graph))

    def test_delta_uses_reading_5_min_ago(self):
        h = History()
        h.extend([(ago(m), 150 - m) for m in range(1, 10)])  # rising 1 mg/dL per min
        self.assertAlmostEqual(h.delta_5min(NOW, 150), 5)

    def test_delta_scales_15_min_graph_points(self):
        h = History()
        h.add(ago(15), 120)
        self.assertAlmostEqual(h.delta_5min(NOW, 150), 10)  # +30 over 15 min

    def test_no_delta_without_recent_history(self):
        h = History()
        h.add(ago(60), 100)
        self.assertIsNone(h.delta_5min(NOW, 150))

    def test_time_in_range_is_time_weighted(self):
        s = GlucoseSettings()
        # In range from 70 to 9 min ago (15-min points), then high at 1-min resolution.
        # Counting points would give 5/15; weighting by time gives 61/70.
        points = [(ago(70 - m), 120) for m in range(0, 61, 15)] + [(ago(10 - m), 250) for m in range(1, 11)]
        self.assertAlmostEqual(time_in_range(points, s), 61 / 70, places=3)


class AlertsTest(unittest.TestCase):
    def test_classify(self):
        s = GlucoseSettings()
        self.assertEqual(classify(50, 4, s), "urgent_low")
        self.assertEqual(classify(65, 4, s), "low")
        self.assertEqual(classify(110, 7, s), "falling_fast")
        self.assertEqual(classify(300, 4, s), "very_high")
        self.assertIsNone(classify(200, 4, s))
        self.assertIsNone(classify(110, 4, s))

    def test_repeat_interval_and_reset(self):
        sent = []
        am = AlertManager(notify=lambda *a: sent.append(a))
        s = GlucoseSettings()
        with mock.patch("src.glucose.alerts.time.time", return_value=1000):
            am.check(65, 4, s)
            am.check(64, 4, s)
        self.assertEqual(len(sent), 1)
        with mock.patch("src.glucose.alerts.time.time", return_value=1000 + 15 * 60):
            am.check(63, 4, s)
        self.assertEqual(len(sent), 2)
        with mock.patch("src.glucose.alerts.time.time", return_value=1000 + 16 * 60):
            am.check(120, 4, s)   # recovered
            am.check(65, 4, s)    # new episode alerts right away
        self.assertEqual(len(sent), 3)
        self.assertFalse(sent[0][2])  # only urgent lows use the looping alarm

    def test_disabled(self):
        sent = []
        am = AlertManager(notify=lambda *a: sent.append(a))
        self.assertIsNone(am.check(40, 4, GlucoseSettings(alerts=False)))
        self.assertEqual(sent, [])


class RenderTest(unittest.TestCase):
    def test_views_produce_png_data_uris(self):
        s = GlucoseSettings()
        hist = [(ago(m), 100 + m) for m in range(180, -1, -5)]
        for uri in (
            render.glucose_image(330, 3, "+6", hist, NOW, s),
            render.glucose_image(48, 7, "-9", hist, NOW, s, inverted=True),
            render.glucose_image(150, 4, "", [], NOW, s, stale_text="hace 23m"),
            render.detail_image([("12h en rango", 18, render.DIM), ("64%", 44, render.HIGH)]),
            render.message_image("Clave mala", render.LOW),
        ):
            self.assertTrue(uri.startswith("data:image/png;base64,"))

    def test_range_colors(self):
        s = GlucoseSettings()
        self.assertEqual(render.range_color(50, s), render.URGENT_LOW)
        self.assertEqual(render.range_color(120, s), render.IN_RANGE)
        self.assertEqual(render.range_color(300, s), render.VERY_HIGH)


@unittest.skipUnless(sys.platform == "win32", "DPAPI is Windows-only")
class SecretsTest(unittest.TestCase):
    def test_roundtrip(self):
        from src.core import secrets
        token = secrets.protect("Clave$con€ñ")
        self.assertNotIn("Clave", token)
        self.assertEqual(secrets.unprotect(token), "Clave$con€ñ")


if __name__ == "__main__":
    unittest.main()
