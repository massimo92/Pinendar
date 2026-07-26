import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Request

from pinendar.application.state import DomainError
from pinendar.infrastructure.auth_store import AccountIdentity

COOKIE_NAME = "pinendar_session"
SESSION_SECONDS = 8 * 60 * 60


def create_session(secret: str, account: AccountIdentity) -> str:
    payload = {
        "accountId": account.id,
        "version": account.session_version,
        "expires": int(time.time()) + SESSION_SECONDS,
        "nonce": secrets.token_hex(16),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def session_payload(token: str | None, secret: str) -> dict[str, object] | None:
    if not token or "." not in token:
        return None
    encoded, signature = token.split(".", 1)
    expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(decoded, dict):
            return None
        payload: dict[str, object] = decoded
        expires = payload.get("expires")
        if not isinstance(expires, int) or expires < int(time.time()):
            return None
        return payload
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def require_auth(request: Request) -> None:
    settings = request.app.state.settings
    payload = session_payload(request.cookies.get(COOKIE_NAME), settings.session_secret)
    if not payload:
        raise DomainError("UNAUTHORIZED", "No autoritzat")
    account = request.app.state.auth_store.get_account(str(payload.get("accountId", "")))
    if (
        not account
        or account.disabled
        or account.session_version != payload.get("version")
    ):
        raise DomainError("UNAUTHORIZED", "No autoritzat")
    if not request.app.state.auth_store.touch_activity(account.id):
        raise DomainError("UNAUTHORIZED", "No autoritzat")
    environment = request.app.state.environments.get(account.environment_path)
    request.state.account = account
    request.state.database = environment.database
    request.state.job_dispatcher = environment.dispatcher
