import asyncio
import hashlib
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
from contextlib import closing
from unittest.mock import patch

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.auth import public_mcp_url
from app.config import settings

ROOT = Path(__file__).resolve().parents[1]


class GuestIntegrationTest(unittest.TestCase):
    def test_public_url_validation(self):
        for value in ('', 'http://example.com/mcp', 'https://localhost/mcp', 'https://localhost./mcp', 'https://127.0.0.1/mcp', 'https://127.1/mcp', 'https://example.com/mcp?token=x'):
            with self.subTest(value=value), patch.object(settings, 'public_mcp_url', value):
                self.assertIsNone(public_mcp_url())
        with patch.object(settings, 'public_mcp_url', 'https://mcp.example.com/mcp'):
            self.assertEqual(public_mcp_url(), 'https://mcp.example.com/mcp')

    def test_two_guest_workspaces_and_mcp_authentication(self):
        with tempfile.TemporaryDirectory() as tmp:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            env = os.environ.copy()
            env.update(DATABASE_URL=f"sqlite:///{(Path(tmp) / 'test.db').as_posix()}", MCP_BEARER_TOKEN=secrets.token_urlsafe(32), OBLIGO_ENV='development', PUBLIC_MCP_URL='https://mcp.example.com/mcp')
            site = Path(sysconfig.get_path('purelib'))
            env['PYTHONPATH'] = os.pathsep.join([str(site), str(site / 'win32'), str(site / 'win32' / 'lib'), str(site / 'pywin32_system32'), env.get('PYTHONPATH', '')])
            proc = subprocess.Popen([sys._base_executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            base = f'http://127.0.0.1:{port}'
            try:
                for _ in range(100):
                    if proc.poll() is not None:
                        self.fail('Server failed to start')
                    try:
                        if httpx.get(base + '/health', timeout=1, trust_env=False).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.1)
                else:
                    self.fail('Server startup timed out')
                asyncio.run(self.exercise_guests(base, env['MCP_BEARER_TOKEN'], Path(tmp) / 'test.db'))
            finally:
                proc.terminate()
                proc.wait(timeout=15)

    async def exercise_guests(self, base, master_token, db_path):
        async with httpx.AsyncClient(base_url=base, trust_env=False, timeout=10) as a, httpx.AsyncClient(base_url=base, trust_env=False, timeout=10) as b:
            login_a = await a.post('/api/session/guest', json={})
            login_b = await b.post('/api/session/guest', json={})
            self.assertEqual(login_a.status_code, 200)
            self.assertEqual(login_b.status_code, 200)
            self.assertIn('HttpOnly', login_a.headers['set-cookie'])
            csrf_a = {'X-CSRF-Token': login_a.json()['csrf_token']}
            csrf_b = {'X-CSRF-Token': login_b.json()['csrf_token']}
            self.assertEqual((await a.get('/api/session')).status_code, 200)
            self.assertEqual((await a.get('/api/session/connection')).json(), {'mcp_url': 'https://mcp.example.com/mcp', 'guest': True})
            self.assertEqual((await a.post('/api/session/mcp-token', json={})).status_code, 403)
            token_a = (await a.post('/api/session/mcp-token', json={}, headers=csrf_a)).json()['token']
            token_b = (await b.post('/api/session/mcp-token', json={}, headers=csrf_b)).json()['token']
            self.assertNotEqual(token_a, token_b)
            async with httpx.AsyncClient(headers={'Authorization': f'Bearer {token_a}'}, trust_env=False, timeout=10) as mcp_a:
                async with streamable_http_client(base + '/mcp', http_client=mcp_a) as (read, write, session_id):
                    async with ClientSession(read, write) as sa:
                        await sa.initialize()
                        created = await sa.call_tool('create_contract', {'vendor_name': 'Guest A vendor', 'title': 'Private contract', 'renewal_date': '2028-01-01', 'notice_period_days': 30})
                        self.assertFalse(created.isError)
                        cid = created.structuredContent['id']
                        added = await sa.call_tool('add_obligation', {'contract_id': cid, 'title': 'Private obligation', 'description': 'Private', 'due_date': '2027-12-01', 'owner': 'A'})
                        self.assertFalse(added.isError)
                        oid = added.structuredContent['id']
                        self.assertIsNone(session_id())
                        async with httpx.AsyncClient(trust_env=False) as attacker:
                            stolen = await attacker.post(base + '/mcp', headers={'Authorization': f'Bearer {token_b}', 'Mcp-Session-Id': 'forged', 'Accept': 'application/json, text/event-stream'}, json={'jsonrpc': '2.0', 'id': 99, 'method': 'tools/list'})
                        self.assertEqual(stolen.status_code, 403)
                        async with httpx.AsyncClient(headers={'Authorization': f'Bearer {token_b}'}, trust_env=False, timeout=10) as mcp_b:
                            async with streamable_http_client(base + '/mcp', http_client=mcp_b) as (r, w, _):
                                async with ClientSession(r, w) as sb:
                                    await sb.initialize()
                                    self.assertEqual((await sb.call_tool('list_contracts', {})).structuredContent['result'], [])
                                    denied = await sb.call_tool('add_obligation', {'contract_id': cid, 'title': 'B', 'description': 'B', 'due_date': '2027-12-01', 'owner': 'B'})
                                    self.assertTrue(denied.isError)
                                    b_created = await sb.call_tool('create_contract', {'vendor_name': 'Guest B vendor', 'title': 'B contract', 'renewal_date': '2028-01-01', 'notice_period_days': 1})
                                    self.assertFalse(b_created.isError)
                                    self.assertEqual(len((await sa.call_tool('list_contracts', {})).structuredContent['result']), 1)
            self.assertEqual(len((await a.get('/api/contracts')).json()), 1)
            self.assertEqual(len((await b.get('/api/contracts')).json()), 1)
            self.assertEqual((await b.get(f'/api/contracts/{cid}')).status_code, 404)
            self.assertEqual((await b.get(f'/api/obligations/{oid}')).status_code, 404)
            self.assertEqual((await b.patch(f'/api/obligations/{oid}', json={'title': 'stolen'}, headers=csrf_b)).status_code, 404)
            self.assertEqual((await a.patch(f'/api/obligations/{oid}', json={'title': 'edited'})).status_code, 403)
            self.assertEqual((await a.patch(f'/api/obligations/{oid}', json={'title': 'edited'}, headers=csrf_a)).status_code, 200)
            self.assertEqual((await a.get('/api/session')).status_code, 200)
            rotated = (await a.post('/api/session/mcp-token', json={}, headers=csrf_a)).json()['token']
            async with httpx.AsyncClient(headers={'Authorization': f'Bearer {token_a}'}, trust_env=False) as old:
                self.assertEqual((await old.post(base + '/mcp')).status_code, 401)
            self.assertEqual((await a.delete('/api/session', headers=csrf_a)).status_code, 200)
            self.assertEqual((await a.get('/api/contracts')).status_code, 401)
            self.assertEqual((await b.get('/api/session')).status_code, 200)
            self.assertEqual((await b.get('/api/dashboard/summary')).json()['total_contracts'], 1)
            async with httpx.AsyncClient(headers={'Authorization': f'Bearer {rotated}'}, trust_env=False) as revoked:
                self.assertEqual((await revoked.post(base + '/mcp')).status_code, 401)
            async with httpx.AsyncClient(headers={'Authorization': f'Bearer {master_token}'}, trust_env=False) as admin:
                async with streamable_http_client(base + '/mcp', http_client=admin) as (r, w, _):
                    async with ClientSession(r, w) as session:
                        await session.initialize()
                        self.assertEqual((await session.call_tool('list_contracts', {})).structuredContent['result'], [])
            async with httpx.AsyncClient(base_url=base, trust_env=False) as expired:
                created_guest = await expired.post('/api/session/guest', json={})
                expired_csrf = {'X-CSRF-Token': created_guest.json()['csrf_token']}
                expired_token = (await expired.post('/api/session/mcp-token', json={}, headers=expired_csrf)).json()['token']
                token_hash = hashlib.sha256(expired_token.encode()).hexdigest()
                with closing(sqlite3.connect(db_path)) as connection:
                    connection.execute('UPDATE guest_workspaces SET expires_at = 1 WHERE mcp_token_hash = ?', (token_hash,))
                    connection.commit()
                self.assertEqual((await expired.get('/api/session')).status_code, 401)
                async with httpx.AsyncClient(headers={'Authorization': f'Bearer {expired_token}'}, trust_env=False) as expired_mcp:
                    self.assertEqual((await expired_mcp.post(base + '/mcp')).status_code, 401)
            for _ in range(27):
                self.assertEqual((await b.post('/api/session/guest', json={})).status_code, 200)
            self.assertEqual((await b.post('/api/session/guest', json={})).status_code, 429)


if __name__ == '__main__':
    unittest.main()
