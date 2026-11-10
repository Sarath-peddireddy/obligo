import asyncio
import hashlib
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
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
from unittest.mock import patch

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.deadlines import deadline_status, workspace_today

ROOT = Path(__file__).resolve().parents[1]


class DeadlineTest(unittest.TestCase):
    def test_status_precedence_and_boundaries(self):
        today = date(2026, 12, 31)
        cases = [
            (True, "pending_review", today - timedelta(days=1), "completed"),
            (False, "pending_review", today - timedelta(days=1), "pending_review"),
            (False, "approved", today - timedelta(days=1), "overdue"),
            (False, "approved", today, "due_today"),
            (False, "approved", today + timedelta(days=1), "due_soon"),
            (False, "approved", today + timedelta(days=7), "due_soon"),
            (False, "approved", today + timedelta(days=8), "upcoming"),
            (False, "approved", None, "unscheduled"),
        ]
        for completed, review, due, expected in cases:
            with self.subTest(expected=expected, due=due):
                self.assertEqual(deadline_status(completed, review, due, today), expected)

    def test_workspace_date_uses_configured_timezone(self):
        instant = datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)
        with patch("app.deadlines.settings.workspace_timezone", "America/Los_Angeles"), patch("app.deadlines.datetime") as clock:
            clock.now.side_effect = lambda zone: instant.astimezone(zone)
            self.assertEqual(workspace_today(), date(2025, 12, 31))


class RESTIntegrationTest(unittest.TestCase):
    def test_mcp_rest_dashboard_and_security(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "workspace.db"
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            token = secrets.token_urlsafe(32)
            env = os.environ.copy()
            env.update(DATABASE_URL=f"sqlite:///{db.as_posix()}", MCP_BEARER_TOKEN=token,
                       OBLIGO_ENV="development", WORKSPACE_TIMEZONE="UTC")
            site = Path(sysconfig.get_path("purelib"))
            env["PYTHONPATH"] = os.pathsep.join([str(site), str(site / "win32"), str(site / "win32" / "lib"), str(site / "pywin32_system32"), env.get("PYTHONPATH", "")])
            process = subprocess.Popen([sys._base_executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            base = f"http://127.0.0.1:{port}"
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        self.fail(f"Server failed: {process.stderr.read()}")
                    try:
                        health = httpx.get(base + "/health", trust_env=False, timeout=1)
                        if health.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.1)
                else:
                    self.fail("Server failed to start")
                self.assertEqual(health.json(), {"status": "ok"})
                today = datetime.now(timezone.utc).date()
                contract, obligations = asyncio.run(self.create_through_mcp(base, token, today))
                self.exercise_rest(base, token, contract, obligations, db)
            finally:
                process.terminate()
                process.wait(timeout=15)
                process.stderr.close()

    async def create_through_mcp(self, base, token, today):
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, trust_env=False) as client:
            async with streamable_http_client(base + "/mcp", http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    created = await session.call_tool("create_contract", {"vendor_name": "Vendor", "title": "Contract", "renewal_date": "2030-01-01", "notice_period_days": 30})
                    self.assertFalse(created.isError)
                    contract = created.structuredContent
                    obligations = []
                    for offset in (-3, 0, 7, 8, -2, 1):
                        result = await session.call_tool("add_obligation", {"contract_id": contract["id"], "title": f"Task {offset}", "description": "Description", "due_date": (today + timedelta(days=offset)).isoformat(), "owner": "Legal"})
                        self.assertFalse(result.isError)
                        obligations.append(result.structuredContent)
                    return contract, obligations

    def exercise_rest(self, base, token, contract, obligations, db):
        with httpx.Client(base_url=base, trust_env=False) as client:
            cid = contract["id"]
            ids = [item["id"] for item in obligations]
            for method, path in [("GET", "/api/contracts"), ("GET", "/api/obligations"), ("GET", "/api/dashboard/summary"), ("PATCH", f"/api/contracts/{cid}"), ("POST", f"/api/obligations/{ids[0]}/complete")]:
                self.assertEqual(client.request(method, path, json={} if method == "PATCH" else None).status_code, 401)
            self.assertEqual(client.post("/api/session", json={"token": "wrong"}).status_code, 401)
            self.assertEqual(client.post("/api/session", json={"token": token}, headers={"Origin": "https://evil.example"}).status_code, 403)
            login = client.post("/api/session", json={"token": token})
            self.assertEqual(login.status_code, 200)
            self.assertIn("HttpOnly", login.headers["set-cookie"])
            self.assertIn("SameSite=strict", login.headers["set-cookie"])
            csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
            self.assertEqual(client.get("/api/session").json(), login.json())
            self.assertEqual(client.get("/api/session", headers={"Origin": "https://evil.example"}).status_code, 403)
            self.assertEqual(client.patch(f"/api/contracts/{cid}", json={"title": "Blocked"}).status_code, 403)
            self.assertEqual(client.patch(f"/api/contracts/{cid}", json={"title": "Blocked"}, headers={"X-CSRF-Token": "wrong"}).status_code, 403)
            self.assertEqual(client.patch(f"/api/contracts/{cid}", json={"title": "Blocked"}, headers={**csrf, "Origin": "https://evil.example"}).status_code, 403)
            self.assertEqual(client.get("/api/contracts").json()[0]["id"], cid)
            self.assertEqual(client.get(f"/api/contracts/{cid}").json()["title"], "Contract")
            self.assertEqual(len(client.get(f"/api/contracts/{cid}/obligations").json()), 6)
            self.assertEqual(len(client.get("/api/obligations").json()), 6)
            self.assertEqual(client.get(f"/api/obligations/{ids[0]}").json()["status"], "pending_review")
            self.assertEqual(client.post(f"/api/obligations/{ids[0]}/complete", headers=csrf).status_code, 409)
            changed = client.patch(f"/api/contracts/{cid}", json={"vendor_name": "Updated", "title": "Updated contract", "renewal_date": "2031-01-01", "notice_period_days": 15}, headers=csrf)
            self.assertEqual(changed.status_code, 200, changed.text)
            saved_contract = client.get(f"/api/contracts/{cid}").json()
            for field in ("vendor_name", "title", "renewal_date", "notice_period_days"):
                self.assertEqual(saved_contract[field], changed.json()[field])
            edited = client.patch(f"/api/obligations/{ids[0]}", json={"title": "Updated task", "description": "Updated description", "owner": "Finance", "due_date": obligations[0]["due_date"], "source_clause": "Clause"}, headers=csrf)
            self.assertEqual(edited.status_code, 200, edited.text)
            for field in ("title", "description", "owner", "due_date", "source_clause"):
                self.assertEqual(client.get(f"/api/obligations/{ids[0]}").json()[field], edited.json()[field])
            for oid in ids[:5]:
                self.assertEqual(client.patch(f"/api/obligations/{oid}", json={"review_status": "approved"}, headers=csrf).status_code, 200)
                self.assertEqual(client.get(f"/api/obligations/{oid}").json()["review_status"], "approved")
            self.assertEqual(client.post(f"/api/obligations/{ids[4]}/complete", headers=csrf).json()["status"], "completed")
            self.assertTrue(client.get(f"/api/obligations/{ids[4]}").json()["is_completed"])
            summary = client.get("/api/dashboard/summary").json()
            self.assertEqual(summary, {"total_contracts": 1, "total_obligations": 6, "pending_review_count": 1, "overdue_count": 1, "due_today_count": 1, "due_soon_count": 1, "completed_count": 1})
            upcoming = client.get("/api/dashboard/upcoming").json()
            self.assertEqual([x["id"] for x in upcoming], ids[:4])
            for path in ("/api/contracts/99999", "/api/contracts/99999/obligations", "/api/obligations/99999"):
                self.assertEqual(client.get(path).status_code, 404)
            self.assertEqual(client.get("/api/contracts/0").status_code, 422)
            for payload in ({"notice_period_days": -1}, {"renewal_date": "2030-02-30"}, {"title": "  "}, {"vendor_name": None}, {"unknown": "x"}, {}):
                self.assertEqual(client.patch(f"/api/contracts/{cid}", json=payload, headers=csrf).status_code, 422)
            self.assertEqual(client.patch(f"/api/obligations/{ids[0]}", json={"review_status": "verified"}, headers=csrf).status_code, 422)
            with httpx.Client(base_url=base, trust_env=False) as expiring:
                self.assertEqual(expiring.post("/api/session", json={"token": token}).status_code, 200)
                cookie_hash = hashlib.sha256(expiring.cookies.get("obligo_session").encode()).hexdigest()
                with closing(sqlite3.connect(db)) as conn:
                    conn.execute("UPDATE browser_sessions SET expires_at = 1 WHERE id_hash = ?", (cookie_hash,))
                    conn.commit()
                self.assertEqual(expiring.get("/api/session").status_code, 401)
            self.assertEqual(client.delete("/api/session", headers=csrf).status_code, 200)
            self.assertEqual(client.get("/api/contracts").status_code, 401)

    def test_separate_workspace_database_and_session_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            processes, urls, tokens = [], [], []
            try:
                for index in range(2):
                    with socket.socket() as sock:
                        sock.bind(("127.0.0.1", 0))
                        port = sock.getsockname()[1]
                    token = secrets.token_urlsafe(32)
                    env = os.environ.copy()
                    env.update(DATABASE_URL=f"sqlite:///{(Path(tmp) / f'{index}.db').as_posix()}", MCP_BEARER_TOKEN=token, OBLIGO_ENV="development", WORKSPACE_TIMEZONE="UTC")
                    site = Path(sysconfig.get_path("purelib"))
                    env["PYTHONPATH"] = os.pathsep.join([str(site), str(site / "win32"), str(site / "win32" / "lib"), str(site / "pywin32_system32"), env.get("PYTHONPATH", "")])
                    proc = subprocess.Popen([sys._base_executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                    processes.append(proc)
                    urls.append(f"http://127.0.0.1:{port}")
                    tokens.append(token)
                    for _ in range(100):
                        if proc.poll() is not None:
                            self.fail(f"Server failed: {proc.stderr.read()}")
                        try:
                            if httpx.get(urls[-1] + "/health", trust_env=False, timeout=1).status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(.1)
                    else:
                        self.fail("Server failed to start")
                asyncio.run(self.create_through_mcp(urls[0], tokens[0], datetime.now(timezone.utc).date()))
                with httpx.Client(base_url=urls[0], trust_env=False) as first, httpx.Client(base_url=urls[1], trust_env=False) as second:
                    self.assertEqual(first.post("/api/session", json={"token": tokens[0]}).status_code, 200)
                    self.assertEqual(len(first.get("/api/contracts").json()), 1)
                    self.assertEqual(second.post("/api/session", json={"token": tokens[0]}).status_code, 401)
                    stolen_cookie = first.cookies.get("obligo_session")
                    second.cookies.set("obligo_session", stolen_cookie)
                    self.assertEqual(second.get("/api/contracts").status_code, 401)
                    second.cookies.clear()
                    self.assertEqual(second.post("/api/session", json={"token": tokens[1]}).status_code, 200)
                    self.assertEqual(second.get("/api/contracts").json(), [])
                    self.assertEqual(second.get("/api/contracts/1").status_code, 404)
            finally:
                for proc in processes:
                    proc.terminate()
                    proc.wait(timeout=15)
                    proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
