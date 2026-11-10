import asyncio
from contextlib import closing
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import sysconfig
import tempfile
import time
import unittest

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


ROOT = Path(__file__).resolve().parents[1]


class MCPIntegrationTest(unittest.TestCase):
    def test_real_http_client_and_database(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "test.db"
            # Exercise the additive migration against a Stage 1 database with existing data.
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("CREATE TABLE contracts (id INTEGER PRIMARY KEY, vendor_name VARCHAR(255) NOT NULL, title VARCHAR(255) NOT NULL, renewal_date DATE, notice_period_days INTEGER, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)")
                conn.execute("INSERT INTO contracts VALUES (1, 'Existing', 'Preserved', NULL, NULL, '2026-01-01', '2026-01-01')")
                conn.commit()
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            token = secrets.token_urlsafe(32)
            env = os.environ.copy()
            env.update(DATABASE_URL=f"sqlite:///{db.as_posix()}", MCP_BEARER_TOKEN=token, OBLIGO_ENV="development", MCP_ALLOWED_ORIGINS="http://127.0.0.1:*,http://localhost:*,http://[::1]:*,https://claude.ai")
            # Windows venv launchers spawn another Python process; launch the real
            # interpreter directly so termination also releases the SQLite file.
            site = Path(sysconfig.get_path("purelib"))
            env["PYTHONPATH"] = os.pathsep.join([str(site), str(site / "win32"), str(site / "win32" / "lib"), str(site / "pywin32_system32"), env.get("PYTHONPATH", "")])
            proc = subprocess.Popen([sys._base_executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                                    cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            base = f"http://127.0.0.1:{port}"
            try:
                for _ in range(100):
                    if proc.poll() is not None:
                        self.fail(f"Backend exited during startup: {proc.stderr.read()}")
                    try:
                        response = httpx.get(base + "/health", timeout=1, trust_env=False)
                        if response.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.1)
                else:
                    self.fail("Backend did not start")
                self.assertEqual(response.json(), {"status": "ok"})
                for method in ("GET", "POST", "DELETE"):
                    for headers in ({}, {"Authorization": "Bearer wrong"}):
                        self.assertEqual(httpx.request(method, base + "/mcp", headers=headers, trust_env=False).status_code, 401)
                rejected = httpx.post(base + "/mcp", headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.example"}, trust_env=False)
                self.assertEqual(rejected.status_code, 400)
                preflight = httpx.options(base + "/mcp", headers={"Origin": "https://claude.ai", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type,mcp-protocol-version"}, trust_env=False)
                self.assertEqual(preflight.status_code, 204)
                self.assertEqual(preflight.headers.get("access-control-allow-origin"), "https://claude.ai")
                self.assertEqual(httpx.options(base + "/mcp", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}, trust_env=False).status_code, 403)
                no_auth = httpx.post(base + "/mcp", headers={"Origin": "https://claude.ai"}, trust_env=False)
                self.assertEqual(no_auth.status_code, 401)
                self.assertEqual(no_auth.headers.get("access-control-allow-origin"), "https://claude.ai")
                self.assertEqual(httpx.get(base + "/mcp", headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}, trust_env=False).status_code, 405)
                init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}
                allowed = httpx.post(base + "/mcp", json=init, headers={"Authorization": f"Bearer {token}", "Origin": "https://claude.ai", "Accept": "application/json, text/event-stream"}, trust_env=False)
                self.assertEqual(allowed.status_code, 200)
                self.assertEqual(allowed.headers.get("access-control-allow-origin"), "https://claude.ai")
                app_origin = httpx.post(base + "/mcp", json=init, headers={"Authorization": f"Bearer {token}", "Origin": "http://localhost:5173", "Accept": "application/json, text/event-stream"}, trust_env=False)
                self.assertEqual(app_origin.status_code, 200)
                self.assertEqual(app_origin.headers.get_list("access-control-allow-origin"), ["http://localhost:5173"])
                asyncio.run(self.exercise_client(base, token, db))
            finally:
                proc.terminate()
                proc.wait(timeout=15)
                proc.stderr.close()

    async def exercise_client(self, base, token, db):
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, trust_env=False, timeout=10) as http:
            async with streamable_http_client(base + "/mcp", http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertEqual({t.name for t in tools.tools}, {"create_contract", "add_obligation", "list_contracts", "list_obligations"})
                    created = await session.call_tool("create_contract", {"vendor_name": "Acme", "title": "Services", "renewal_date": "2027-04-02", "notice_period_days": 30, "source_clause": "Renew annually"})
                    self.assertFalse(created.isError, str(created))
                    contract = created.structuredContent
                    self.assertEqual(contract["source_clause"], "Renew annually")
                    added = await session.call_tool("add_obligation", {"contract_id": contract["id"], "title": "Notify", "description": "Send notice", "due_date": "2027-03-01", "owner": "Legal", "source_clause": "Notice clause"})
                    self.assertFalse(added.isError, str(added))
                    obligation = added.structuredContent
                    self.assertEqual(obligation["review_status"], "pending_review")
                    contracts = await session.call_tool("list_contracts", {})
                    obligations = await session.call_tool("list_obligations", {"contract_id": contract["id"]})
                    self.assertFalse(contracts.isError)
                    self.assertFalse(obligations.isError)
                    self.assertIn(contract, contracts.structuredContent["result"])
                    self.assertIn(obligation, obligations.structuredContent["result"])
                    for name, args in [
                        ("create_contract", {"vendor_name": "  ", "title": "X", "renewal_date": "2027-01-01", "notice_period_days": 1}),
                        ("create_contract", {"vendor_name": "X", "title": "X", "renewal_date": "2027-02-30", "notice_period_days": 1}),
                        ("create_contract", {"vendor_name": "X", "title": "X", "renewal_date": "2027-01-01", "notice_period_days": -1}),
                        ("add_obligation", {"contract_id": 999999, "title": "X", "description": "X", "due_date": "2027-01-01", "owner": "X"}),
                        ("list_obligations", {"contract_id": "1"}),
                    ]:
                        result = await session.call_tool(name, args)
                        self.assertTrue(result.isError, f"Invalid input accepted by {name}")
            # Reconnect with a fresh MCP session and retrieve the committed data.
            async with streamable_http_client(base + "/mcp", http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    fresh = await session.call_tool("list_obligations", {"contract_id": contract["id"]})
                    self.assertFalse(fresh.isError)
                    self.assertIn(obligation, fresh.structuredContent["result"])
        # A separate database connection establishes committed persistence and migration.
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute("SELECT title FROM contracts WHERE id=1").fetchone(), ("Preserved",))
            self.assertEqual(conn.execute("SELECT vendor_name, source_clause FROM contracts WHERE id=?", (contract["id"],)).fetchone(), ("Acme", "Renew annually"))
            self.assertEqual(conn.execute("SELECT contract_id, review_status FROM obligations WHERE id=?", (obligation["id"],)).fetchone(), (contract["id"], "pending_review"))

    def test_production_requires_token(self):
        with tempfile.TemporaryDirectory() as directory:
            env = os.environ.copy()
            env.update(DATABASE_URL=f"sqlite:///{Path(directory).as_posix()}/test.db", MCP_BEARER_TOKEN="", OBLIGO_ENV="production")
            result = subprocess.run([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "0"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("MCP_BEARER_TOKEN must be configured", result.stderr)

    def test_production_rejects_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            env = os.environ.copy()
            env.update(DATABASE_URL=f"sqlite:///{Path(directory).as_posix()}/test.db", MCP_BEARER_TOKEN=secrets.token_urlsafe(32), OBLIGO_ENV="production", CORS_ORIGINS="https://frontend.example", MCP_ALLOWED_HOSTS="backend.example", MCP_ALLOWED_ORIGINS="https://frontend.example")
            result = subprocess.run([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "0"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Production requires PostgreSQL", result.stderr)


if __name__ == "__main__":
    unittest.main()
