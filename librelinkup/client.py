import base64
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

REGION_URLS = {
    "us":  "https://api.libreview.io",
    "eu":  "https://api-eu.libreview.io",
    "eu2": "https://api-eu2.libreview.io",
    "ap":  "https://api-ap.libreview.io",
    "ap2": "https://api-ap2.libreview.io",
    "la":  "https://api-la.libreview.io",
    "ca":  "https://api-ca.libreview.io",
}

DEFAULT_BASE_URL = "https://api.libreview.io"

BASE_HEADERS = {
    "User-Agent":      "FreeStyle LibreLink Up iOS 4.16.0",
    "product":         "llu.ios",
    "version":         "4.16.0",
    "Content-Type":    "application/json",
    "Accept":          "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
    "Pragma":          "no-cache",
    "Cache-Control":   "no-cache",
}

TREND_ARROWS = {1: "↑↑", 2: "↑", 3: "↗", 4: "→", 5: "↘", 6: "↓", 7: "↓↓"}
TREND_LABELS = {
    1: "Subiendo rapido", 2: "Subiendo", 3: "Subiendo lento",
    4: "Estable", 5: "Bajando lento", 6: "Bajando", 7: "Bajando rapido",
}


class LibreLinkUpError(RuntimeError):
    """Generic API failure (network, unexpected payload, server error)."""


class AuthError(LibreLinkUpError):
    """Credentials rejected. Retrying with the same credentials will not help."""


class RateLimitError(LibreLinkUpError):
    """Account temporarily locked after too many failed logins."""

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class TermsError(LibreLinkUpError):
    """User must accept new terms / privacy policy in the LibreLinkUp app."""


def _parse_timestamp(value: str) -> datetime | None:
    # FactoryTimestamp is UTC, e.g. "9/27/2026 10:54:57 PM"
    try:
        return datetime.strptime(value, "%m/%d/%Y %I:%M:%S %p").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _decode_jwt_payload(token: str) -> dict:
    part = token.split(".")[1]
    part += "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part))


def _token_cache_path() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, ".llu_token_cache.json")


class LibreLinkUpClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self._token: str | None = None
        self._account_id: str | None = None
        self._base_url = DEFAULT_BASE_URL
        self._session = requests.Session()
        self._session.headers.update(BASE_HEADERS)
        self._load_cache()

    # ------------------------------------------------------------------
    # Token cache (avoids re-login on every plugin restart)
    # ------------------------------------------------------------------

    def _load_cache(self):
        try:
            path = _token_cache_path()
            if not os.path.exists(path):
                return
            with open(path, "r") as f:
                data = json.load(f)
            token = data.get("token")
            if not token:
                return
            claims = _decode_jwt_payload(token)
            if time.time() > claims.get("exp", 0) - 300:
                return  # expired or expiring soon
            self._token      = token
            self._account_id = data.get("account_id")
            self._base_url   = data.get("base_url", DEFAULT_BASE_URL)
        except Exception:
            pass

    def _save_cache(self):
        try:
            with open(_token_cache_path(), "w") as f:
                json.dump({
                    "token":      self._token,
                    "account_id": self._account_id,
                    "base_url":   self._base_url,
                }, f)
        except Exception:
            pass

    def _clear_cache(self):
        try:
            path = _token_cache_path()
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _is_token_expired(self) -> bool:
        if not self._token:
            return True
        try:
            claims = _decode_jwt_payload(self._token)
            return time.time() > claims.get("exp", 0) - 300
        except Exception:
            return True

    def _post_login(self, base_url: str) -> dict:
        resp = self._session.post(
            f"{base_url}/llu/auth/login",
            json={"email": self.email, "password": self.password}, timeout=15,
        )
        try:
            data = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise LibreLinkUpError(f"Login: invalid response (HTTP {resp.status_code})")

        status = data.get("status")
        if status == 429 or resp.status_code == 429:
            lock = data.get("data", {}).get("data", {})
            raise RateLimitError("Account locked after failed logins", int(lock.get("lockout", 300)))
        if status == 2:
            msg = data.get("error", {}).get("message", "incorrect username/password")
            raise AuthError(f"Login rejected: {msg}")
        if status == 4:
            raise TermsError("Open the LibreLinkUp app and accept the new terms")
        resp.raise_for_status()
        return data

    def login(self) -> None:
        # Step 1: global endpoint to discover region
        data = self._post_login(DEFAULT_BASE_URL)

        if data.get("data", {}).get("redirect"):
            region = data["data"].get("region", "us")
        elif data.get("status") == 0 and data.get("data", {}).get("authTicket"):
            token_tmp = data["data"]["authTicket"]["token"]
            region = _decode_jwt_payload(token_tmp).get("region", "us")
        else:
            raise LibreLinkUpError(f"Login step 1 failed: status={data.get('status')}")
        self._base_url = REGION_URLS.get(region, DEFAULT_BASE_URL)

        # Step 2: login directly on the regional endpoint
        if self._base_url != DEFAULT_BASE_URL:
            data = self._post_login(self._base_url)

        auth_ticket = data.get("data", {}).get("authTicket")
        if data.get("status") != 0 or not auth_ticket:
            raise LibreLinkUpError(f"Login failed: status={data.get('status')}")

        payload       = data["data"]
        self._token   = auth_ticket["token"]
        raw_id        = payload.get("user", {}).get("id") or payload.get("accountId")
        self._account_id = hashlib.sha256(raw_id.encode()).hexdigest() if raw_id else None
        self._save_cache()

    def _auth_headers(self) -> dict:
        if self._is_token_expired():
            self.login()
        headers = {"Authorization": f"Bearer {self._token}"}
        if self._account_id:
            headers["account-id"] = self._account_id
        return headers

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _get(self, path: str) -> dict | list:
        url = f"{self._base_url}{path}"
        resp = self._session.get(url, headers=self._auth_headers(), timeout=15)

        if resp.status_code in (401, 403):
            self._token = None
            self._account_id = None
            self._clear_cache()
            url = f"{self._base_url}{path}"
            resp = self._session.get(url, headers=self._auth_headers(), timeout=15)

        resp.raise_for_status()
        data = resp.json()

        if data.get("status") == 4:
            raise TermsError("Open the LibreLinkUp app and accept the new terms")
        if data.get("status") != 0:
            raise LibreLinkUpError(f"GET {path} failed: status={data.get('status')}")

        return data.get("data")

    def get_connections(self) -> list[dict]:
        return self._get("/llu/connections") or []

    def get_patients(self) -> list[dict]:
        """People this account follows: [{"id", "name"}]."""
        return [
            {"id": c.get("patientId"),
             "name": f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()}
            for c in self.get_connections()
        ]

    def get_latest_glucose(self, patient_id: str | None = None) -> dict | None:
        connection = _pick_connection(self.get_connections(), patient_id)
        if connection is None:
            return None
        return _reading(connection.get("glucoseMeasurement"))

    def get_glucose_with_history(self, patient_id: str | None = None) -> dict | None:
        """Latest reading plus the last ~12 h of history (15-min resolution)."""
        if patient_id is None:
            connection = _pick_connection(self.get_connections(), None)
            if connection is None:
                return None
            patient_id = connection.get("patientId")

        data = self._get(f"/llu/connections/{patient_id}/graph") or {}
        connection = data.get("connection") or {}
        current = _reading(connection.get("glucoseMeasurement"))
        if current is None:
            return None

        history = []
        for point in data.get("graphData") or []:
            at    = _parse_timestamp(point.get("FactoryTimestamp", ""))
            value = point.get("ValueInMgPerDl")
            if at is not None and value is not None:
                history.append((at, value))
        history.sort()

        current["patient_id"]   = patient_id
        current["patient_name"] = connection.get("firstName", "")
        current["history"]      = history
        return current


def _pick_connection(connections: list[dict], patient_id: str | None) -> dict | None:
    if not connections:
        return None
    if patient_id:
        for c in connections:
            if c.get("patientId") == patient_id:
                return c
    return connections[0]


def _reading(gm: dict | None) -> dict | None:
    if not gm:
        return None
    trend = gm.get("TrendArrow", 4)
    return {
        # "Value" is in the account's display unit (mg/dL or mmol/L); always use mg/dL
        "value":       gm.get("ValueInMgPerDl") or gm.get("Value"),
        "trend":       trend,
        "trend_arrow": TREND_ARROWS.get(trend, "→"),
        "trend_label": TREND_LABELS.get(trend, "Estable"),
        "is_high":     gm.get("isHigh", False),
        "is_low":      gm.get("isLow", False),
        "timestamp":   gm.get("Timestamp", ""),
        "measured_at": _parse_timestamp(gm.get("FactoryTimestamp", "")),
    }
