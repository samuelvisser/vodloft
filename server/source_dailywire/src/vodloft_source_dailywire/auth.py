"""Daily Wire device authentication without application config or token storage."""

import json
import time
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from source_contracts import AuthenticationChallenge, AuthenticationResult

ISSUER = "https://authorize.dailywire.com"
CLIENT_ID = "FCgw3nA6cxkcXLVseAQvCSVBrymwvfpE"
AUDIENCE = "https://api.dailywire.com/"
SCOPE = "openid profile offline_access"


def _post(path: str, fields: dict) -> dict:
    request = Request(ISSUER + path, data=urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=25) as response:
            return json.loads(response.read(1024 * 1024))
    except HTTPError as exc:
        if exc.code in (400, 401, 403):
            return json.loads(exc.read(1024 * 1024))
        raise


def start() -> AuthenticationResult:
    data = _post("/oauth/device/code", {"client_id": CLIENT_ID, "scope": SCOPE, "audience": AUDIENCE})
    expires = time.time() + int(data["expires_in"])
    return AuthenticationResult(status="pending", interval=int(data.get("interval", 5)),
        expires_at=expires, private_state={"device_code": data["device_code"], "expires_at": expires},
        challenge=AuthenticationChallenge(kind="device_code", message="Authorize this Source account",
            verification_url=data.get("verification_uri_complete") or data["verification_uri"],
            user_code=data["user_code"], expires_at=datetime.fromtimestamp(expires, timezone.utc)))


def _authorized(data: dict, existing_refresh: str | None = None) -> AuthenticationResult:
    return AuthenticationResult(status="authorized", expires_at=time.time() + int(data.get("expires_in", 3600)) - 30,
        configuration={"access_token": data["access_token"]},
        private_state={"refresh_token": data.get("refresh_token") or existing_refresh})


def poll(state: dict) -> AuthenticationResult:
    if float(state.get("expires_at", 0)) <= time.time():
        return AuthenticationResult(status="expired")
    data = _post("/oauth/token", {"client_id": CLIENT_ID,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code", "device_code": state["device_code"]})
    if data.get("access_token"):
        return _authorized(data)
    error = data.get("error")
    if error in ("authorization_pending", "slow_down"):
        interval = min(120, int(state.get("interval", 5)) + (5 if error == "slow_down" else 0))
        return AuthenticationResult(status="pending", private_state={**state, "interval": interval},
            expires_at=float(state["expires_at"]), interval=interval)
    return AuthenticationResult(status="expired" if error == "expired_token" else "denied")


def refresh(state: dict) -> AuthenticationResult:
    token = state.get("refresh_token")
    if not token:
        return AuthenticationResult(status="expired")
    data = _post("/oauth/token", {"client_id": CLIENT_ID, "grant_type": "refresh_token", "refresh_token": token})
    return _authorized(data, token) if data.get("access_token") else AuthenticationResult(status="expired")
