"""Read-only MCP interoperability probe; guest credentials never leave memory."""
import asyncio
from pathlib import Path

import httpx
from dotenv import dotenv_values
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

BASE = "https://obligo-workspace-api.vercel.app"
ORIGIN = "https://obligo-workspace.vercel.app"
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-11-25", "capabilities": {},
    "clientInfo": {"name": "obligo-interoperability-probe", "version": "1.0"}}}


async def run():
    async with httpx.AsyncClient(base_url=BASE, timeout=45, trust_env=False, follow_redirects=False) as browser:
        guest = await browser.post("/api/session/guest", json={}, headers={"Origin": ORIGIN})
        assert guest.status_code == 200, f"guest sign-in HTTP {guest.status_code}"
        csrf = {"X-CSRF-Token": guest.json()["csrf_token"], "Origin": ORIGIN}
        result = await browser.post("/api/session/mcp-token", json={}, headers=csrf)
        assert result.status_code == 200, f"credential HTTP {result.status_code}"
        token = result.json()["token"]
        try:
            unauth = await browser.post("/mcp", json=INIT, headers={"Accept": "application/json, text/event-stream"})
            print("Unauthenticated POST:", unauth.status_code, "challenge:", unauth.headers.get("www-authenticate", "none"))
            legacy = dotenv_values(Path(__file__).resolve().parents[1] / ".env").get("MCP_BEARER_TOKEN")
            if legacy:
                old = await browser.post("/mcp", json=INIT, headers={"Authorization": f"Bearer {legacy}", "Accept": "application/json, text/event-stream"})
                print("Local .env credential against public MCP:", old.status_code)
            headers = {"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream"}
            first = await browser.post("/mcp", json=INIT, headers=headers)
            payload = first.json()
            print("Initialize:", first.status_code, "type:", first.headers.get("content-type"), "negotiated:", payload.get("result", {}).get("protocolVersion"), "session header:", "present" if first.headers.get("mcp-session-id") else "absent", "redirect:", first.is_redirect)
            assert first.status_code == 200 and "result" in payload and not first.headers.get("mcp-session-id")
            for label, extra in [("no Origin", {}), ("Claude Origin", {"Origin": "https://claude.ai"}), ("app Origin", {"Origin": ORIGIN}), ("untrusted Origin", {"Origin": "https://untrusted.example"})]:
                response = await browser.post("/mcp", json=INIT, headers={**headers, **extra})
                print(label + ":", response.status_code)
            for version in ("2025-11-25", "2025-06-18", "2025-03-26", "1900-01-01"):
                response = await browser.post("/mcp", json={"jsonrpc":"2.0", "id":2, "method":"tools/list"}, headers={**headers, "MCP-Protocol-Version": version})
                print("Protocol header", version + ":", response.status_code)
            try:
                async with asyncio.timeout(8):
                    async with browser.stream("GET", "/mcp", headers={"Authorization": "Bearer " + token, "Accept": "text/event-stream"}) as standalone:
                        print("Authenticated GET:", standalone.status_code, "type:", standalone.headers.get("content-type", "none"))
            except TimeoutError:
                print("Authenticated GET: timed out waiting for response headers")
            unsupported = await browser.put("/mcp", headers=headers)
            print("Authenticated PUT:", unsupported.status_code)
            preflight = await browser.options("/mcp", headers={"Origin": "https://claude.ai", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type,mcp-protocol-version"})
            print("Claude-origin preflight:", preflight.status_code)
            missing_accept = await browser.post("/mcp", json=INIT, headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
            print("JSON-only Accept:", missing_accept.status_code)
            for index in range(2):
                async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}, timeout=45, trust_env=False) as transport:
                    async with streamable_http_client(BASE + "/mcp", http_client=transport) as (read, write, get_id):
                        async with ClientSession(read, write) as session:
                            handshake = await session.initialize()
                            tools = await session.list_tools()
                            call = await session.call_tool("list_contracts", {})
                            assert len(tools.tools) == 4 and not call.isError and get_id() is None
                            print("Independent SDK connection", index + 1, ": PASS; protocol", handshake.protocolVersion, "; tools/list and tools/call PASS")
        finally:
            logout = await browser.delete("/api/session", headers=csrf)
            print("Disposable guest revoked:", logout.status_code)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as exc:
        print("Probe failed:", type(exc).__name__)
        raise SystemExit(1)
