"""Signed OAuth2 state helpers for AgentArts User Federation callbacks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from app.settings import Settings


class OAuth2StateError(ValueError):
    """Raised when an OAuth2 state value is missing, invalid, or expired."""


@dataclass(frozen=True, slots=True)
class OAuth2StateClaims:
    """Verified OAuth2 state claims."""

    user_id: str
    session_id: str
    provider: str
    nonce: str
    exp: int


_COMPLETED_NONCES: dict[str, int] = {}
_ACTIVE_NONCES: dict[str, int] = {}


def create_oauth2_state(
    *,
    settings: Settings,
    user_id: str,
    session_id: str,
    provider: str,
    now: float | None = None,
) -> str:
    """Create a compact HMAC-signed OAuth2 state string."""
    issued_at = int(now if now is not None else time.time())
    claims = {
        "user_id": user_id,
        "session_id": session_id,
        "provider": provider,
        "nonce": secrets.token_urlsafe(16),
        "exp": issued_at + settings.oauth2_pending_auth_ttl_seconds,
    }
    payload = _b64encode_json(claims)
    signature = _sign(payload, settings.oauth2_state_secret)
    return f"{payload}.{signature}"


def verify_oauth2_state(
    state: str,
    *,
    settings: Settings,
    expected_user_id: str | None = None,
    expected_provider: str,
    now: float | None = None,
) -> OAuth2StateClaims:
    """Verify an OAuth2 state string and return its claims."""
    if not state or "." not in state:
        raise OAuth2StateError("invalid OAuth2 state")

    payload, signature = state.rsplit(".", maxsplit=1)
    expected_signature = _sign(payload, settings.oauth2_state_secret)
    if not hmac.compare_digest(signature, expected_signature):
        raise OAuth2StateError("invalid OAuth2 state signature")

    try:
        raw_claims = _b64decode_json(payload)
        claims = OAuth2StateClaims(
            user_id=_required_str(raw_claims, "user_id"),
            session_id=_required_str(raw_claims, "session_id"),
            provider=_required_str(raw_claims, "provider"),
            nonce=_required_str(raw_claims, "nonce"),
            exp=int(raw_claims["exp"]),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise OAuth2StateError("invalid OAuth2 state claims") from e

    current_time = int(now if now is not None else time.time())
    if claims.exp < current_time:
        raise OAuth2StateError("OAuth2 state expired")
    if expected_user_id is not None and claims.user_id != expected_user_id:
        raise OAuth2StateError("OAuth2 state user mismatch")
    if claims.provider != expected_provider:
        raise OAuth2StateError("OAuth2 state provider mismatch")

    _prune_completed_nonces(current_time)
    return claims


def is_oauth2_state_completed(claims: OAuth2StateClaims) -> bool:
    """Return whether this OAuth2 state nonce has already completed."""
    _prune_completed_nonces(int(time.time()))
    return claims.nonce in _COMPLETED_NONCES


def mark_oauth2_state_active(claims: OAuth2StateClaims) -> bool:
    """Mark a nonce as actively completing, returning false for duplicates."""
    _prune_completed_nonces(int(time.time()))
    if claims.nonce in _COMPLETED_NONCES or claims.nonce in _ACTIVE_NONCES:
        return False
    _ACTIVE_NONCES[claims.nonce] = claims.exp
    return True


def mark_oauth2_state_completed(claims: OAuth2StateClaims) -> None:
    """Record a successfully completed OAuth2 state nonce for replay handling."""
    _COMPLETED_NONCES[claims.nonce] = claims.exp
    _ACTIVE_NONCES.pop(claims.nonce, None)


def clear_oauth2_state_active(claims: OAuth2StateClaims) -> None:
    """Release an active nonce when completion fails before it is finalized."""
    _ACTIVE_NONCES.pop(claims.nonce, None)


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64encode_bytes(digest)


def _b64encode_json(value: dict[str, Any]) -> str:
    return _b64encode_bytes(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )


def _b64decode_json(value: str) -> dict[str, Any]:
    padded = value + "=" * (-len(value) % 4)
    decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
    parsed = json.loads(decoded)
    if not isinstance(parsed, dict):
        raise ValueError("state payload must be a JSON object")
    return parsed


def _b64encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _required_str(claims: dict[str, Any], key: str) -> str:
    value = claims[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _prune_completed_nonces(now: int) -> None:
    expired = [nonce for nonce, exp in _COMPLETED_NONCES.items() if exp < now]
    for nonce in expired:
        _COMPLETED_NONCES.pop(nonce, None)
    expired_active = [nonce for nonce, exp in _ACTIVE_NONCES.items() if exp < now]
    for nonce in expired_active:
        _ACTIVE_NONCES.pop(nonce, None)
