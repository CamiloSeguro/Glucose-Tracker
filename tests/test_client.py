import base64
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import librelinkup.client as c
from librelinkup.client import AuthError, LibreLinkUpClient, RateLimitError, TermsError


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body, self.status_code = body, status_code

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def jwt(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({})}.{enc(claims)}.sig"


def factory_ts(dt: datetime) -> str:
    return dt.strftime("%m/%d/%Y %I:%M:%S %p")


class ClientTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(c, "_token_cache_path",
                                    return_value=os.path.join(self._tmp.name, "cache.json"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def client(self, post=None, get=None) -> LibreLinkUpClient:
        cl = LibreLinkUpClient("a@b.c", "secret")
        if post is not None:
            cl._session.post = mock.Mock(side_effect=post)
        if get is not None:
            cl._session.get = mock.Mock(side_effect=get)
        return cl

    def logged_in(self, **kw) -> LibreLinkUpClient:
        tok = jwt({"exp": time.time() + 3600, "region": "eu"})
        return self.client(post=[
            FakeResponse({"status": 0, "data": {"redirect": True, "region": "eu"}}),
            FakeResponse({"status": 0, "data": {"authTicket": {"token": tok}, "user": {"id": "u1"}}}),
        ], **kw)

    def test_bad_credentials_raise_auth_error(self):
        cl = self.client(post=[FakeResponse({"status": 2, "error": {"message": "incorrect username/password"}})])
        with self.assertRaises(AuthError):
            cl.login()

    def test_lockout_raises_rate_limit_with_retry_after(self):
        body = {"status": 429, "data": {"code": 60, "data": {"failures": 3, "interval": 60, "lockout": 300}}}
        cl = self.client(post=[FakeResponse(body, 429)])
        with self.assertRaises(RateLimitError) as ctx:
            cl.login()
        self.assertEqual(ctx.exception.retry_after, 300)

    def test_pending_terms_raise_terms_error(self):
        cl = self.client(post=[FakeResponse({"status": 4, "data": {"step": {}}})])
        with self.assertRaises(TermsError):
            cl.login()

    def test_region_redirect_and_account_id_header(self):
        cl = self.logged_in(get=[FakeResponse({"status": 0, "data": []})])
        cl.get_connections()
        self.assertEqual(cl._base_url, c.REGION_URLS["eu"])
        headers = cl._session.get.call_args.kwargs["headers"]
        self.assertEqual(len(headers["account-id"]), 64)  # sha256 hex of the user id

    def test_value_uses_mgdl_even_for_mmol_accounts(self):
        gm = {"Value": 6.1, "ValueInMgPerDl": 110, "GlucoseUnits": 0, "TrendArrow": 4,
              "FactoryTimestamp": factory_ts(datetime.now(timezone.utc))}
        cl = self.logged_in(get=[FakeResponse({"status": 0, "data": [{"patientId": "p1", "glucoseMeasurement": gm}]})])
        self.assertEqual(cl.get_latest_glucose()["value"], 110)

    def test_graph_history_sorted_and_parsed(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        graph = {
            "connection": {"firstName": "Ana", "glucoseMeasurement": {
                "ValueInMgPerDl": 120, "TrendArrow": 3, "FactoryTimestamp": factory_ts(now)}},
            "graphData": [
                {"ValueInMgPerDl": 100, "FactoryTimestamp": factory_ts(now - timedelta(minutes=15))},
                {"ValueInMgPerDl": 90,  "FactoryTimestamp": factory_ts(now - timedelta(minutes=30))},
            ],
        }
        cl = self.logged_in(get=[FakeResponse({"status": 0, "data": graph})])
        r = cl.get_glucose_with_history("p1")
        self.assertEqual(r["value"], 120)
        self.assertEqual(r["patient_name"], "Ana")
        self.assertEqual([v for _, v in r["history"]], [90, 100])
        self.assertIn("/llu/connections/p1/graph", cl._session.get.call_args.args[0])

    def test_expired_session_relogs_once(self):
        cl = self.logged_in(get=[FakeResponse({}, 401), FakeResponse({"status": 0, "data": []})])
        cl._token = jwt({"exp": time.time() + 3600})
        self.assertEqual(cl.get_connections(), [])
        self.assertEqual(cl._session.post.call_count, 2)  # region discovery + regional login


if __name__ == "__main__":
    unittest.main()
