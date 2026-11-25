import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional, Dict, Any, Callable
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

JWT_SECRET = os.getenv("IERS_JWT_SECRET", "iers-hubballi-dharwad-dev-secret-2026")
JWT_TTL_SECONDS = 60 * 60 * 12  # 12 hours

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256$120000${salt}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iters_s, salt, hex_digest = stored_hash.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iters_s))
        return hmac.compare_digest(dk.hex(), hex_digest)
    except Exception:
        return False


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def create_access_token(payload: Dict[str, Any]) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body_dict = {**payload, "iat": int(time.time()), "exp": int(time.time()) + JWT_TTL_SECONDS}
    body = _b64url(json.dumps(body_dict, separators=(",", ":")).encode())
    sig = _b64url(hmac.new(JWT_SECRET.encode("utf-8"), f"{header}.{body}".encode("ascii"), hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, body, sig = parts
        expected = _b64url(hmac.new(JWT_SECRET.encode("utf-8"), f"{header}.{body}".encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return payload


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[Dict[str, Any]]:
    if not credentials or not credentials.credentials:
        return None
    return decode_access_token(credentials.credentials)


def require_roles(*allowed_roles: str) -> Callable:
    async def _checker(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.get('role')}' is not permitted for this operation. Allowed: {', '.join(allowed_roles)}",
            )
        return user
    return _checker
