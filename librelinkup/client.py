import base64
import hashlib
import json
import os
import sys
import time
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

    def login(self) -> None:
        body = {"email": self.email, "password": self.password}

        # Step 1: global endpoint to discover region
        resp = requests.post(
            f"{DEFAULT_BASE_URL}/llu/auth/login",
            json=body, headers=BASE_HEADERS, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("data", {}).get("redirect"):
            # Redirect can come with status=0 or status=2
            region = data["data"].get("region", "us")
            self._base_url = REGION_URLS.get(region, DEFAULT_BASE_URL)
        elif data.get("status") == 0:
            token_tmp = data["data"]["authTicket"]["token"]
            region = _decode_jwt_payload(token_tmp).get("region", "us")
            self._base_url = REGION_URLS.get(region, DEFAULT_BASE_URL)
        else:
            raise RuntimeError(f"Login step 1 failed: {data}")

        # Step 2: login directly on the regional endpoint
        if self._base_url != DEFAULT_BASE_URL:
            resp = requests.post(
                f"{self._base_url}/llu/auth/login",
                json=body, headers=BASE_HEADERS, timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != 0:
            raise RuntimeError(f"Login failed: {data}")

        payload       = data["data"]
        self._token   = payload["authTicket"]["token"]
        raw_id        = payload.get("user", {}).get("id") or payload.get("accountId")
        self._account_id = hashlib.sha256(raw_id.encode()).hexdigest() if raw_id else None
        self._save_cache()

    def _auth_headers(self) -> dict:
        if self._is_token_expired():
            self.login()
        headers = {**BASE_HEADERS, "Authorization": f"Bearer {self._token}"}
        if self._account_id:
            headers["account-id"] = self._account_id
        return headers

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def get_connections(self) -> list[dict]:
        headers = self._auth_headers()
        url = f"{self._base_url}/llu/connections"
        resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code in (401, 403):
            self._token = None
            self._account_id = None
            self._clear_cache()
            headers = self._auth_headers()
            url = f"{self._base_url}/llu/connections"
            resp = requests.get(url, headers=headers, timeout=15)

        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != 0:
            raise RuntimeError(f"Could not fetch connections: {data}")

        return data.get("data", [])

    def get_latest_glucose(self) -> dict | None:
        connections = self.get_connections()
        if not connections:
            return None

        gm = connections[0].get("glucoseMeasurement")
        if not gm:
            return None

        trend = gm.get("TrendArrow", 4)
        return {
            "value":       gm.get("Value") or gm.get("ValueInMgPerDl"),
            "trend":       trend,
            "trend_arrow": TREND_ARROWS.get(trend, "→"),
            "trend_label": TREND_LABELS.get(trend, "Estable"),
            "is_high":     gm.get("isHigh", False),
            "is_low":      gm.get("isLow", False),
            "timestamp":   gm.get("Timestamp", ""),
        }
