"""ComfyUI Studio — Cookie functions, AuthMiddleware, login/logout endpoints."""

import hashlib
import hmac as hmac_mod
import secrets

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

import os
from config import app, SESSION_SECRET_PATH

def _api_key():
    return os.environ.get("API_KEY", "changeme")

# ── Auth ─────────────────────────────────────────────────────────────────────

COOKIE_NAME = "session"
COOKIE_MAX_AGE = 86400  # 24h


def _load_or_create_secret() -> str:
    if SESSION_SECRET_PATH.exists():
        return SESSION_SECRET_PATH.read_text().strip()
    secret = secrets.token_hex(64)
    SESSION_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_SECRET_PATH.write_text(secret)
    return secret


COOKIE_SECRET = _load_or_create_secret()


def _sign_cookie(value: str) -> str:
    # Include timestamp for expiration check
    from datetime import datetime, timezone
    ts = int(datetime.now(timezone.utc).timestamp())
    payload = f"{value}:{ts}"
    sig = hmac_mod.new(COOKIE_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}.{sig}"


def _verify_cookie(cookie: str) -> bool:
    if "." not in cookie:
        return False
    payload, sig = cookie.rsplit(".", 1)
    expected = hmac_mod.new(COOKIE_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac_mod.compare_digest(sig, expected):
        return False
    # Check expiration
    parts = payload.split(":")
    if len(parts) >= 2:
        try:
            from datetime import datetime, timezone
            ts = int(parts[-1])
            age = int(datetime.now(timezone.utc).timestamp()) - ts
            if age > COOKIE_MAX_AGE:
                return False
        except (ValueError, TypeError):
            return False
    return True


_maintenance_mode = False


class AuthMiddleware(BaseHTTPMiddleware):
    PUBLIC_PATHS = {"/login", "/api/auth/login", "/api/health"}
    PUBLIC_PREFIXES = ("/api/health", "/static/")

    async def dispatch(self, request, call_next):
        global _maintenance_mode
        if _maintenance_mode:
            path = request.url.path
            if path.startswith("/api/"):
                return JSONResponse({"detail": "System is updating, please wait..."}, status_code=503)
            return HTMLResponse(
                '<html><body style="background:#0a0a0f;color:#e8ff47;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh;font-size:18px;">'
                '<div style="text-align:center;">Updating...<br><span style="font-size:12px;color:#888;">The system is downloading updates. This page will reload automatically.</span>'
                '<script>setTimeout(function(){location.reload()},3000)</script></div></body></html>',
                status_code=503,
            )

        path = request.url.path

        # Public paths
        if path in self.PUBLIC_PATHS:
            return await call_next(request)
        for prefix in self.PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # X-API-Key header (for curl/scripts)
        api_key_header = request.headers.get("X-API-Key", "")
        if api_key_header and secrets.compare_digest(api_key_header, _api_key()):
            return await call_next(request)

        # Session cookie (with sliding expiration)
        cookie = request.cookies.get(COOKIE_NAME, "")
        if cookie and _verify_cookie(cookie):
            response = await call_next(request)
            # Renew cookie on each request (sliding expiration)
            response.set_cookie(
                COOKIE_NAME,
                _sign_cookie("authenticated"),
                httponly=True,
                secure=True,
                samesite="strict",
                path="/",
                max_age=COOKIE_MAX_AGE,
            )
            return response

        # Not authenticated
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return RedirectResponse(f"/login?next={path}", status_code=302)


app.add_middleware(AuthMiddleware)


# ── Auth endpoints ───────────────────────────────────────────────────────────


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    from catalogs import _www
    return HTMLResponse(_www("login.html").read_text())


@app.post("/api/auth/login")
async def auth_login(request: Request):
    body = await request.json()
    key = body.get("api_key", "")
    if not secrets.compare_digest(key.encode(), _api_key().encode()):
        raise HTTPException(401, "Invalid API key")
    next_url = body.get("next", "/home")
    response = JSONResponse({"status": "ok", "redirect": next_url})
    response.set_cookie(
        COOKIE_NAME,
        _sign_cookie("authenticated"),
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
        max_age=COOKIE_MAX_AGE,
    )
    return response


@app.post("/api/auth/logout")
async def auth_logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
