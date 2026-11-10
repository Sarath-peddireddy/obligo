"""Persistent, revocable single-workspace browser sessions."""
import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, select, text
from urllib.parse import urlsplit
import ipaddress

from app.config import settings
from app.database import SessionLocal
from app.models import BrowserSession, GuestWorkspace, GuestAttempt
from app.demo_data import seed_demo_workspace

router = APIRouter(prefix="/api/session", tags=["session"])
COOKIE = "obligo_session"
SESSION_SECONDS = 8 * 60 * 60
GUEST_SECONDS = 48 * 60 * 60


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def csrf_for(session_id: str) -> str:
    return hmac.new(session_id.encode("utf-8"), b"obligo-csrf-v1", hashlib.sha256).hexdigest()


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in settings.allowed_origins:
        raise HTTPException(status_code=403, detail="Origin not allowed")


def require_session(request: Request) -> str | None:
    session_id = request.cookies.get(COOKIE, "")
    if not session_id or len(session_id) > 256:
        raise HTTPException(status_code=401, detail="Authentication required")
    with SessionLocal() as db:
        session = db.get(BrowserSession, digest(session_id))
        workspace_id = session.workspace_id if session is not None else None
        guest = db.get(GuestWorkspace, workspace_id) if workspace_id else None
        valid = (session is not None and session.expires_at > int(time.time()) and
                 ((guest is not None and guest.expires_at > int(time.time())) if workspace_id else
                  (bool(settings.mcp_bearer_token.strip()) and hmac.compare_digest(session.credential_hash, digest(settings.mcp_bearer_token)))))
    if not valid:
        raise HTTPException(status_code=401, detail="Authentication required")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        check_origin(request)
        supplied = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(supplied.encode(), csrf_for(session_id).encode()):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return workspace_id


def public_mcp_url() -> str | None:
    url = settings.public_mcp_url.strip()
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        _ = parts.port  # Reject malformed ports.
        if parts.scheme != "https" or not host or parts.username or parts.password or parts.path != "/mcp" or parts.query or parts.fragment or host == "localhost" or host.endswith((".localhost", ".local")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if "." not in host or all(char.isdigit() or char == "." for char in host):
                return None
        return url
    except ValueError:
        return None


@router.get("/connection")
def connection_info(response: Response, workspace: str | None = Depends(require_session)):
    response.headers["Cache-Control"] = "no-store"
    return {"mcp_url": public_mcp_url(), "guest": workspace is not None}


@router.post("/mcp-token")
def create_guest_token(response: Response, workspace: str | None = Depends(require_session)):
    if workspace is None:
        raise HTTPException(status_code=403, detail="Guest session required")
    token = secrets.token_urlsafe(32)
    with SessionLocal() as db:
        guest = db.get(GuestWorkspace, workspace)
        if guest is None or guest.expires_at <= int(time.time()):
            raise HTTPException(status_code=401, detail="Session expired")
        expires_at = guest.expires_at
        guest.mcp_token_hash = digest(token)
        db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"token": token, "expires_at": expires_at}


@router.post("/guest")
async def guest_login(request: Request, response: Response):
    check_origin(request)
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Expected JSON")
    now = int(time.time())
    client_hash = digest(request.client.host if request.client else "unknown")
    session_id, workspace_id = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with SessionLocal() as db:
        # Serialize rate-limit checks across processes, including concurrent requests.
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(782393104)"))
        elif db.bind.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        db.execute(delete(GuestAttempt).where(GuestAttempt.created_at <= now - 86400))
        recent = db.scalar(select(func.count()).select_from(GuestAttempt).where(GuestAttempt.client_hash == client_hash, GuestAttempt.created_at > now - 3600))
        total = db.scalar(select(func.count()).select_from(GuestAttempt))
        if recent >= 30 or total >= 1000:
            raise HTTPException(status_code=429, detail="Guest sign-in limit reached. Try again later.")
        db.add(GuestAttempt(client_hash=client_hash, created_at=now))
        db.add(GuestWorkspace(id=workspace_id, expires_at=now + GUEST_SECONDS))
        db.add(BrowserSession(id_hash=digest(session_id), credential_hash="", workspace_id=workspace_id, expires_at=now + GUEST_SECONDS))
        if settings.seed_demo_workspace:
            seed_demo_workspace(db, workspace_id)
        db.commit()
    response.set_cookie(COOKIE, session_id, max_age=GUEST_SECONDS, httponly=True,
                        secure=settings.obligo_env.lower() == "production", samesite="strict", path="/api")
    response.headers["Cache-Control"] = "no-store"
    return {"csrf_token": csrf_for(session_id)}


@router.get("", dependencies=[Depends(require_session)])
def current_session(request: Request, response: Response):
    check_origin(request)
    response.headers["Cache-Control"] = "no-store"
    return {"csrf_token": csrf_for(request.cookies[COOKIE])}


@router.post("")
async def login(request: Request, response: Response):
    check_origin(request)
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Expected JSON")
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request") from None
    token = data.get("token") if isinstance(data, dict) and set(data) == {"token"} else None
    expected = settings.mcp_bearer_token
    if not isinstance(token, str) or not expected.strip() or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    session_id = secrets.token_urlsafe(32)
    now = int(time.time())
    with SessionLocal() as db:
        db.execute(delete(BrowserSession).where(BrowserSession.expires_at <= now))
        old = request.cookies.get(COOKIE)
        if old and len(old) <= 256:
            db.execute(delete(BrowserSession).where(BrowserSession.id_hash == digest(old)))
        db.add(BrowserSession(id_hash=digest(session_id), credential_hash=digest(expected), expires_at=now + SESSION_SECONDS))
        db.commit()
    response.set_cookie(COOKIE, session_id, max_age=SESSION_SECONDS, httponly=True,
                        secure=settings.obligo_env.lower() == "production", samesite="strict", path="/api")
    response.headers["Cache-Control"] = "no-store"
    return {"csrf_token": csrf_for(session_id)}


@router.delete("", dependencies=[Depends(require_session)])
def logout(request: Request, response: Response):
    with SessionLocal() as db:
        session = db.get(BrowserSession, digest(request.cookies[COOKIE]))
        if session and session.workspace_id:
            guest = db.get(GuestWorkspace, session.workspace_id)
            if guest:
                guest.mcp_token_hash = None
        db.execute(delete(BrowserSession).where(BrowserSession.id_hash == digest(request.cookies[COOKIE])))
        db.commit()
    response.delete_cookie(COOKIE, path="/api", httponly=True,
                           secure=settings.obligo_env.lower() == "production", samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"status": "signed_out"}
