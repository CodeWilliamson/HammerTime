"""Authentication — direct port of ``auth.js``.

JWT is stored in an httpOnly cookie named ``token`` (1 hour, SameSite=Strict).

Deliberate deviation from the Node version: ``JWT_SECRET`` is read from the environment
*after* ``.env`` has been loaded. In the original ESM app ``auth.js`` evaluated before
``dotenv.config()`` ran, so ``.env``'s ``JWT_SECRET`` was silently ignored and the
default secret was always used. Honouring ``.env`` is the intended behaviour; existing
sessions are invalidated on cutover.
"""

from __future__ import annotations

import os
from typing import Any, Dict

import bcrypt
import jwt
from fastapi import APIRouter, Request

from hammertime import clock
from hammertime.db import get_user_by_username, update_password
from hammertime.responses import JSONResponse
from hammertime.web import read_json

router = APIRouter()

DEFAULT_SECRET = "timertimertimer"
TOKEN_TTL_SECONDS = 60 * 60  # 1 hour


class AuthError(Exception):
    """Raised by :func:`require_auth`; rendered as 403 ``{"error": ...}``."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def secret() -> str:
    # Mirrors `process.env.JWT_SECRET || "timertimertimer"` (empty string falls back).
    return os.environ.get("JWT_SECRET") or DEFAULT_SECRET


def _check_password(password: Any, password_hash: Any) -> bool:
    return bcrypt.checkpw(
        str(password).encode("utf-8"), str(password_hash).encode("utf-8")
    )


@router.post("/auth/login")
async def login(request: Request):
    body: Dict[str, Any] = await read_json(request)
    username = body.get("username")
    password = body.get("password")

    # `.toLowerCase()` on a non-string raises in Node (500); keep the same failure mode.
    user = get_user_by_username(str(username).lower())
    if user is None or not _check_password(password, user["password_hash"]):
        return JSONResponse({"error": "Invalid credentials"}, status_code=401)

    issued_at = int(clock.now().timestamp())
    token = jwt.encode(
        {"user": username, "iat": issued_at, "exp": issued_at + TOKEN_TTL_SECONDS},
        secret(),
        algorithm="HS256",
    )

    response = JSONResponse({"success": True})
    response.set_cookie(
        "token",
        token,
        max_age=TOKEN_TTL_SECONDS,
        path="/",
        httponly=True,
        samesite="strict",
    )
    return response


@router.post("/auth/change-password")
async def change_password(request: Request):
    body: Dict[str, Any] = await read_json(request)
    username = body.get("username")
    old_password = body.get("oldPassword")
    new_password = body.get("newPassword")

    lowered = str(username).lower()
    user = get_user_by_username(lowered)
    if user is None or not _check_password(old_password, user["password_hash"]):
        return JSONResponse({"error": "Invalid credentials"}, status_code=401)

    success = update_password(lowered, new_password)
    if not success:
        return JSONResponse({"error": "Failed to update password"}, status_code=500)

    response = JSONResponse({"success": success})
    # Byte-identical to Express's `res.clearCookie("token", {httpOnly: true,
    # sameSite: "strict"})` — note the unquoted empty value and no Max-Age.
    response.headers["set-cookie"] = (
        "token=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; "
        "HttpOnly; SameSite=Strict"
    )
    return response


async def require_auth(request: Request) -> None:
    """Auth middleware: 403 ``{"error": ...}`` when the cookie is missing or invalid."""
    token = request.cookies.get("token")
    if not token:
        raise AuthError("No token")

    try:
        # Expiry is validated against the server clock (like jsonwebtoken's Date.now())
        # rather than wall time inside PyJWT, so the frozen-clock parity tests and the
        # production behaviour share one code path.
        decoded = jwt.decode(
            token,
            secret(),
            algorithms=["HS256"],
            options={"verify_exp": False, "verify_nbf": False, "verify_iat": False},
        )
    except jwt.PyJWTError:
        raise AuthError("Invalid or expired token")

    expires_at = decoded.get("exp")
    if isinstance(expires_at, (int, float)) and expires_at <= clock.now().timestamp():
        # jsonwebtoken treats `exp <= now` as expired.
        raise AuthError("Invalid or expired token")

    request.state.user = decoded.get("user")
