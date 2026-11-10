from contextlib import asynccontextmanager
import hmac
import re
import time
from sqlalchemy import select

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from app import models  # noqa: F401 - register tables with metadata
from app.config import settings
from app.database import engine
from app.mcp_server import mcp
from app.migrations import initialize_database
from app.routes.health import router as health_router
from app.routes.api import router as api_router
from app.auth import router as auth_router
from app.services import NotFoundError, ConflictError
from app.auth import digest
from app.database import SessionLocal
from app.models import GuestWorkspace
from app.workspace_context import workspace_context

mcp_app = mcp.streamable_http_app()


class MCPBearerAuth:
    """Protect every MCP transport request, including session GET and DELETE."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and (scope["path"] == "/mcp" or scope["path"].startswith("/mcp/")):
            origin_headers = [v for k, v in scope["headers"] if k.lower() == b"origin"]
            try:
                origin = origin_headers[0].decode("ascii") if len(origin_headers) == 1 else ""
            except UnicodeDecodeError:
                origin = ""
            allowed_origin = bool(origin) and any(
                origin == allowed or (allowed.endswith(":*") and re.fullmatch(re.escape(allowed[:-2]) + r":\d+", origin))
                for allowed in settings.allowed_mcp_origins
            )

            async def send_with_cors(message):
                if message["type"] == "http.response.start" and allowed_origin:
                    headers = [(key, value) for key, value in message.get("headers", [])
                               if key.lower() not in (b"access-control-allow-origin", b"access-control-allow-credentials")]
                    headers.extend([(b"access-control-allow-origin", origin.encode("ascii")),
                                    (b"access-control-allow-credentials", b"true"),
                                    (b"vary", b"Origin")])
                    message = {**message, "headers": headers}
                await send(message)

            if scope["method"] == "OPTIONS" and origin_headers:
                values = {k.lower(): v for k, v in scope["headers"]}
                method = values.get(b"access-control-request-method", b"").upper()
                requested = {x.strip().lower() for x in values.get(b"access-control-request-headers", b"").split(b",") if x.strip()}
                permitted = {b"authorization", b"content-type", b"accept", b"mcp-protocol-version", b"mcp-session-id", b"last-event-id"}
                if not allowed_origin or method not in (b"GET", b"POST", b"DELETE") or not requested.issubset(permitted):
                    await JSONResponse({"detail": "Origin or method not allowed"}, status_code=403)(scope, receive, send)
                    return
                await Response(status_code=204, headers={"Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Credentials": "true", "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept, MCP-Protocol-Version, MCP-Session-Id, Last-Event-ID",
                    "Vary": "Origin, Access-Control-Request-Method, Access-Control-Request-Headers"})(scope, receive, send)
                return
            token = settings.mcp_bearer_token
            headers = [v for k, v in scope["headers"] if k.lower() == b"authorization"]
            expected = b"Bearer " + token.encode("utf-8")
            master = bool(token.strip()) and len(headers) == 1 and hmac.compare_digest(headers[0], expected)
            workspace = None
            authorized = master
            if not master and len(headers) == 1 and headers[0].startswith(b"Bearer "):
                try:
                    candidate = headers[0][7:].decode("ascii")
                    if len(candidate) <= 256:
                        with SessionLocal() as db:
                            guest = db.scalar(select(GuestWorkspace).where(GuestWorkspace.mcp_token_hash == digest(candidate), GuestWorkspace.expires_at > int(time.time())))
                            if guest:
                                workspace, authorized = guest.id, True
                except UnicodeDecodeError:
                    pass
            if not authorized:
                response = JSONResponse({"detail": "Unauthorized"}, status_code=401,
                                        headers={"WWW-Authenticate": "Bearer"})
                await response(scope, receive, send_with_cors)
                return
            if scope["method"] == "GET":
                # This stateless server has no server-initiated messages. Keeping
                # a standalone SSE stream open can hit serverless time limits.
                await Response(status_code=405, headers={"Allow": "POST, OPTIONS"})(scope, receive, send_with_cors)
                return
            session_headers = [v for k, v in scope["headers"] if k.lower() == b"mcp-session-id"]
            if session_headers:
                await JSONResponse({"detail": "Invalid session"}, status_code=403)(scope, receive, send_with_cors)
                return
            marker = workspace_context.set(workspace)
            try:
                await self.app(scope, receive, send_with_cors)
            finally:
                workspace_context.reset(marker)
            return
        await self.app(scope, receive, send)


def validate_production_settings(dialect: str) -> None:
    if settings.obligo_env.lower() == "production":
        if len(settings.mcp_bearer_token.strip()) < 32:
            raise RuntimeError("MCP_BEARER_TOKEN must be configured in production with at least 32 characters")
        if dialect != "postgresql":
            raise RuntimeError("Production requires PostgreSQL DATABASE_URL")
        def valid_origin(origin: str) -> bool:
            parsed = urlsplit(origin)
            return bool(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
                        and not parsed.path and not parsed.query and not parsed.fragment and "*" not in origin)
        if not settings.allowed_origins or any(not valid_origin(o) for o in settings.allowed_origins):
            raise RuntimeError("Production CORS_ORIGINS must contain explicit HTTPS origins")
        if not settings.allowed_mcp_hosts or any(any(char in host for char in "*/?#@ ") or "localhost" in host.lower() or "127.0.0.1" in host for host in settings.allowed_mcp_hosts):
            raise RuntimeError("Production MCP_ALLOWED_HOSTS must contain explicit public hosts")
        if any(not valid_origin(origin) for origin in settings.allowed_mcp_origins):
            raise RuntimeError("Production MCP_ALLOWED_ORIGINS must contain explicit HTTPS origins")


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production_settings(engine.dialect.name)
    ZoneInfo(settings.workspace_timezone)
    initialize_database()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Obligo API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(api_router)


@app.exception_handler(NotFoundError)
async def not_found_handler(request, exc):
    return JSONResponse({"detail": "Record not found"}, status_code=404)


@app.exception_handler(ConflictError)
async def conflict_handler(request, exc):
    return JSONResponse({"detail": "Approve the obligation before completing it"}, status_code=409)


app.add_middleware(MCPBearerAuth)
app.mount("/", mcp_app)
