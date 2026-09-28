import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from librelinkup.client import AuthError, RateLimitError
from src.glucose import service as svc_mod


def reading(value=120, minutes_ago=1, trend=4, history=()):
    return {
        "value": value, "trend": trend, "is_low": False, "is_high": False,
        "measured_at": datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        "history": list(history), "patient_name": "Ana",
    }


class ServiceTest(unittest.TestCase):
    def setUp(self):
        patches = [
            mock.patch.object(svc_mod.threading, "Thread"),      # no background polling loop
            mock.patch.object(svc_mod, "load_env"),
            mock.patch.dict(os.environ, {"LLU_EMAIL": "a@b.c", "LLU_PASSWORD": "x"}),
            mock.patch("src.glucose.alerts.show_toast"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.plugin = mock.Mock()
        self.svc = svc_mod.GlucoseService(self.plugin)
        self.client = mock.Mock()

    def fetch(self, force=False):
        return self.svc._fetch(self.client, None, force)

    def test_credentials_from_env(self):
        self.assertEqual(self.svc.public_state()["source"], ".env")

    def test_bad_password_backs_off_until_forced(self):
        self.client.get_glucose_with_history.side_effect = AuthError("bad")
        self.assertEqual(self.fetch().error, "Clave mala")
        self.assertIsNone(self.fetch())
        self.assertIsNone(self.fetch())
        self.assertEqual(self.client.get_glucose_with_history.call_count, 1)
        self.fetch(force=True)
        self.assertEqual(self.client.get_glucose_with_history.call_count, 2)

    def test_lockout_blocks_even_forced_refresh(self):
        self.client.get_glucose_with_history.side_effect = RateLimitError("locked", 300)
        self.assertEqual(self.fetch().error, "Bloqueado")
        self.assertIsNone(self.fetch(force=True))
        self.assertEqual(self.client.get_glucose_with_history.call_count, 1)

    def test_snapshot_has_delta_and_history(self):
        at = datetime.now(timezone.utc)
        hist = [(at - timedelta(minutes=16), 100)]
        self.client.get_glucose_with_history.return_value = {**reading(130, 1, history=hist), "measured_at": at - timedelta(minutes=1)}
        snap = self.fetch()
        self.assertIsNone(snap.error)
        self.assertAlmostEqual(snap.delta, 10)  # +30 over 15 min
        self.assertEqual(len(snap.history), 2)

    def test_stale_low_reading_does_not_alert(self):
        self.client.get_glucose_with_history.return_value = reading(50, minutes_ago=40)
        self.assertIsNone(self.fetch().alert)
        self.client.get_glucose_with_history.return_value = reading(50, minutes_ago=1)
        self.assertEqual(self.fetch().alert, "urgent_low")

    def test_panel_credentials_override_env_and_are_encrypted(self):
        with mock.patch.object(svc_mod.secrets, "protect", return_value="ENC"), \
             mock.patch.object(svc_mod.secrets, "unprotect", return_value="newpass"):
            self.svc.save_credentials("new@b.c", "newpass")
        stored = self.plugin.set_global_settings.call_args.args[0]
        self.assertEqual(stored["password_enc"], "ENC")
        self.assertNotIn("newpass", str(stored))
        state = self.svc.public_state()
        self.assertEqual((state["email"], state["source"]), ("new@b.c", "panel"))
        self.assertNotIn("newpass", str(state))


if __name__ == "__main__":
    unittest.main()
