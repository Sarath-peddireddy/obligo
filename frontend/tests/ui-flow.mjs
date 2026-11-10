// End-to-end smoke test: starts isolated backend and Vite instances with disposable data.
import { chromium } from 'playwright'
import { spawn, execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdtempSync, rmSync } from 'node:fs'
import net from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const backend = path.resolve(frontend, '..', 'backend')
const temp = mkdtempSync(path.join(tmpdir(), 'obligo-ui-'))
const python = process.platform === 'win32' ? path.join(backend, '.venv', 'Scripts', 'python.exe') : path.join(backend, '.venv', 'bin', 'python')
const info = JSON.parse(execFileSync(python, ['-c', 'import json,sys,sysconfig; print(json.dumps([sys._base_executable,sysconfig.get_path("purelib")]))'], { encoding: 'utf8' }))
const site = info[1]
const token = randomBytes(32).toString('base64url')
const env = { ...process.env, DATABASE_URL: `sqlite:///${path.join(temp, 'test.db').replaceAll('\\', '/')}`, MCP_BEARER_TOKEN: token, OBLIGO_ENV: 'development', WORKSPACE_TIMEZONE: 'UTC', PYTHONPATH: [site, path.join(site, 'win32'), path.join(site, 'win32', 'lib'), path.join(site, 'pywin32_system32'), process.env.PYTHONPATH || ''].join(path.delimiter) }
let server, vite, browser
async function waitFor(url, child) { for (let i = 0; i < 120; i++) { if (child.exitCode !== null) throw new Error(`Server exited: ${url}`); try { if ((await fetch(url)).ok) return } catch {} await new Promise(r => setTimeout(r, 250)) } throw new Error(`Timed out: ${url}`) }
async function freePort() { return new Promise((resolve, reject) => { const probe = net.createServer(); probe.once('error', reject); probe.listen(0, '127.0.0.1', () => { const port = probe.address().port; probe.close(() => resolve(port)) }) }) }
function assert(value, message) { if (!value) throw new Error(message) }
try {
  const backendPort = await freePort()
  let frontendPort = await freePort()
  while (frontendPort === backendPort) frontendPort = await freePort()
  const backendUrl = `http://127.0.0.1:${backendPort}`
  const frontendUrl = `http://127.0.0.1:${frontendPort}`
  env.CORS_ORIGINS = frontendUrl
  env.OBLIGO_TEST_URL = backendUrl
  server = spawn(info[0], ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(backendPort)], { cwd: backend, env, stdio: 'ignore' })
  await waitFor(`${backendUrl}/health`, server)
  const seed = `import asyncio, os, httpx\nfrom datetime import datetime, timezone, timedelta\nfrom mcp import ClientSession\nfrom mcp.client.streamable_http import streamable_http_client\nfrom app.services import ObligationPatch, update_obligation\nasync def seed():\n today=datetime.now(timezone.utc).date()\n async with httpx.AsyncClient(headers={'Authorization': 'Bearer '+os.environ['MCP_BEARER_TOKEN']}, trust_env=False) as client:\n  async with streamable_http_client(os.environ['OBLIGO_TEST_URL']+'/mcp',http_client=client) as (read,write,_):\n   async with ClientSession(read,write) as session:\n    await session.initialize()\n    result=await session.call_tool('create_contract',{'vendor_name':'Acme Labs','title':'Platform agreement','renewal_date':'2028-04-20','notice_period_days':30})\n    assert not result.isError\n    cid=result.structuredContent['id']\n    result=await session.call_tool('add_obligation',{'contract_id':cid,'title':'Send renewal notice','description':'Send notice to vendor','due_date':'2028-03-20','owner':'Legal','source_clause':'Written notice required.'})\n    assert not result.isError\n    for title,offset,owner in [('Confirm insurance coverage',-3,'Operations'),('Submit usage report',0,'Finance'),('Review service levels',5,'Legal')]:\n     result=await session.call_tool('add_obligation',{'contract_id':cid,'title':title,'description':'Contractual requirement','due_date':(today+timedelta(days=offset)).isoformat(),'owner':owner,'source_clause':'Refer to the agreement.'})\n     assert not result.isError\n     update_obligation(result.structuredContent['id'],ObligationPatch(review_status='approved'))\nasyncio.run(seed())`
  vite = spawn(process.execPath, [path.join(frontend, 'node_modules', 'vite', 'bin', 'vite.js'), '--host', '127.0.0.1', '--port', String(frontendPort), '--strictPort'], { cwd: frontend, env: { ...process.env, VITE_API_URL: '', OBLIGO_PROXY_TARGET: backendUrl }, stdio: 'ignore' })
  await waitFor(`${frontendUrl}/`, vite)
  const chrome = process.env.CHROME_PATH || (process.platform === 'win32' ? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' : undefined)
  browser = await chromium.launch({ headless: true, ...(chrome ? { executablePath: chrome } : {}) })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: frontendUrl })
  const page = await context.newPage()
  await page.goto(`${frontendUrl}/`)
  for (const [label, width, height] of [['desktop', 1440, 1000], ['laptop', 1280, 900], ['mobile', 390, 844]]) { await page.setViewportSize({ width, height }); await page.screenshot({ path: path.join(temp, `login-${label}.png`) }) }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByRole('button', { name: 'Continue as Guest' }).click()
  await page.getByRole('heading', { name: 'No contracts yet' }).waitFor()
  await page.getByRole('button', { name: 'Connect Claude' }).first().click()
  await page.getByRole('dialog', { name: 'Connect Claude' }).waitFor()
  await page.getByText('MCP endpoint not configured yet.').waitFor()
  await page.getByRole('button', { name: 'Copy prompt' }).click()
  const copiedPrompt = (await page.evaluate(() => navigator.clipboard.readText())).replaceAll('\r\n', '\n')
  assert(copiedPrompt === `Create a contract in Obligo for Acme Cloud Services.\n\nContract title: Annual Software Agreement\nRenewal date: 2027-03-15\nCancellation notice: 30 days\n\nAdd an obligation:\nTitle: Review cancellation deadline\nDescription: Decide whether to renew or cancel the vendor agreement.\nDue date: 2027-02-13\nOwner: Finance Manager\n\nUse the Obligo MCP tools to save this information.`, 'Sample prompt copy mismatch')
  await page.getByRole('button', { name: 'Close connection guide' }).click()
  await page.reload()
  await page.getByRole('heading', { name: 'No contracts yet' }).waitFor()
  await page.locator('summary').click()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.getByRole('button', { name: 'Continue as Guest' }).waitFor()
  await new Promise(resolve => { server.once('exit', resolve); server.kill() })
  env.PUBLIC_MCP_URL = 'https://mcp.example.com/mcp'
  server = spawn(info[0], ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(backendPort)], { cwd: backend, env, stdio: 'ignore' })
  await waitFor(`${backendUrl}/health`, server)
  await page.getByRole('button', { name: 'Continue as Guest' }).click()
  await page.getByRole('heading', { name: 'No contracts yet' }).waitFor()
  await page.getByRole('button', { name: 'Connect Claude' }).first().click()
  await page.getByText('https://mcp.example.com/mcp').waitFor()
  await page.screenshot({ path: path.join(temp, 'guide-desktop.png') })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.screenshot({ path: path.join(temp, 'guide-laptop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: path.join(temp, 'guide-mobile.png') })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByRole('button', { name: 'Copy URL' }).click()
  assert(await page.evaluate(() => navigator.clipboard.readText()) === 'https://mcp.example.com/mcp', 'Configured MCP URL copy mismatch')
  await page.getByRole('button', { name: 'Create guest credential' }).click()
  await page.getByRole('button', { name: 'Copy header' }).click()
  const guestHeader = await page.evaluate(() => navigator.clipboard.readText())
  assert(guestHeader.startsWith('Bearer ') && !guestHeader.includes(token), 'Guest header was missing or contained the master token')
  await page.getByRole('button', { name: 'Close connection guide' }).click()
  await page.getByRole('button', { name: 'Contracts', exact: true }).click()
  await page.getByRole('heading', { name: 'Contracts', exact: true }).waitFor()
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await page.locator('summary').click()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.getByRole('button', { name: 'Continue as Guest' }).waitFor()
  const signInWorkspace = async () => { const status = await page.evaluate(async value => { const response = await fetch('/api/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: value }) }); if (response.ok) sessionStorage.setItem('obligo.signedIn', '1'); return response.status }, token); assert(status === 200, 'Workspace session setup failed'); await page.reload(); await page.getByRole('heading', { name: 'Overview' }).waitFor() }
  await signInWorkspace()
  const secondTab = await context.newPage()
  await secondTab.goto(`${frontendUrl}/`)
  await secondTab.getByRole('heading', { name: 'Overview' }).waitFor()
  assert(await secondTab.evaluate(() => sessionStorage.getItem('obligo.csrf')) === null, 'CSRF token unexpectedly stored in sessionStorage')
  await page.getByRole('heading', { name: 'No contracts yet' }).waitFor()
  for (const [label, width, height] of [['desktop', 1440, 1000], ['laptop', 1280, 900], ['mobile', 390, 844]]) { await page.setViewportSize({ width, height }); await page.waitForTimeout(300); await page.screenshot({ path: path.join(temp, `empty-${label}.png`), fullPage: true }) }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByRole('button', { name: 'Connect Claude' }).first().click()
  await page.getByRole('dialog', { name: 'Connect Claude' }).waitFor()
  await page.getByRole('button', { name: 'Close connection guide' }).click()
  execFileSync(info[0], ['-c', seed], { cwd: backend, env, stdio: 'pipe' })
  await page.getByRole('button', { name: 'Refresh' }).click()
  await page.getByText('Platform agreement').first().waitFor()
  await new Promise(resolve => { server.once('exit', resolve); server.kill() })
  server = spawn(info[0], ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(backendPort)], { cwd: backend, env, stdio: 'ignore' })
  await waitFor(`${backendUrl}/health`, server)
  await secondTab.reload()
  await secondTab.getByRole('heading', { name: 'Overview' }).waitFor()
  await secondTab.getByText('Platform agreement').first().waitFor()
  for (const [label, width, height] of [['desktop', 1440, 1000], ['laptop', 1280, 900], ['mobile', 390, 844]]) { await page.setViewportSize({ width, height }); await page.waitForTimeout(300); await page.screenshot({ path: path.join(temp, `populated-${label}.png`), fullPage: true }) }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByRole('button', { name: 'Collapse sidebar' }).click()
  await page.getByRole('button', { name: 'Expand sidebar' }).click()
  await page.getByRole('button', { name: 'Contracts', exact: true }).click()
  await page.getByRole('heading', { name: 'Contracts', exact: true }).waitFor()
  for (const [label, width, height] of [['desktop', 1440, 1000], ['laptop', 1280, 900], ['mobile', 390, 844]]) { await page.setViewportSize({ width, height }); await page.screenshot({ path: path.join(temp, `contracts-${label}.png`), fullPage: true }) }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.locator('.table-name').filter({ hasText: 'Acme Labs' }).click()
  await page.getByRole('heading', { name: 'Platform agreement' }).waitFor()
  await page.getByRole('button', { name: 'Edit contract' }).click()
  await page.getByLabel('Contract title').fill('Updated agreement')
  await page.getByRole('button', { name: 'Save changes' }).click()
  await page.getByText('Contract updated successfully.').waitFor()
  await page.reload()
  await page.getByRole('heading', { name: 'Updated agreement' }).waitFor()
  await page.getByRole('button', { name: 'Obligations', exact: true }).click()
  await page.getByRole('heading', { name: 'Obligations', exact: true }).waitFor()
  for (const [label, width, height] of [['desktop', 1440, 1000], ['laptop', 1280, 900], ['mobile', 390, 844]]) { await page.setViewportSize({ width, height }); await page.screenshot({ path: path.join(temp, `obligations-${label}.png`), fullPage: true }) }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByLabel('Search obligations').fill('renewal')
  await page.getByLabel('Filter by status').selectOption('pending_review')
  await page.getByLabel('Filter by owner').selectOption('Legal')
  await page.getByRole('button', { name: 'Sort due date descending' }).click()
  await page.getByRole('button', { name: 'Send renewal notice', exact: true }).click()
  await page.getByRole('button', { name: 'Edit obligation' }).click()
  await page.getByLabel('Title', { exact: true }).fill('Updated notice')
  await page.getByRole('button', { name: 'Save changes' }).click()
  await page.getByText('Obligation updated successfully.').waitFor()
  await page.reload()
  await page.getByRole('heading', { name: 'Updated notice' }).waitFor()
  await page.getByRole('button', { name: 'Approve obligation' }).click()
  await page.getByText('Obligation approved.').waitFor()
  await page.getByRole('button', { name: 'Mark complete' }).click()
  await page.getByText('Obligation marked complete.').waitFor()
  await page.reload()
  await page.getByText('Completed', { exact: true }).waitFor()
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await page.getByRole('heading', { name: 'Claude integration' }).waitFor()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Open navigation' }).click()
  assert(await page.getByRole('navigation', { name: 'Main navigation' }).isVisible(), 'Mobile navigation did not open')
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(temp, 'mobile.png') })
  await page.getByRole('button', { name: 'Overview', exact: true }).click()
  await page.getByRole('heading', { name: 'Overview' }).waitFor()
  await page.getByRole('button', { name: 'Open navigation' }).click()
  await page.locator('summary').click()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.getByRole('button', { name: 'Continue as Guest' }).waitFor()
  await secondTab.reload()
  await secondTab.getByRole('button', { name: 'Continue as Guest' }).waitFor()
  await signInWorkspace()
  await context.clearCookies()
  await page.reload()
  await page.getByText('Your session has expired. Please sign in again.').waitFor()
  console.log(`PASS: guest sign-in and workspace session, multi-tab, guide, configured/missing MCP URL, clipboard, edits, approval, completion, mobile navigation, sign-out, and expiry. Screenshots: ${temp}`)
} finally {
  await browser?.close()
  await Promise.all([vite, server].filter(Boolean).map(child => new Promise(resolve => { if (child.exitCode !== null) return resolve(); child.once('exit', resolve); child.kill() })))
  // Keep screenshots for inspection; remove only this test's disposable database.
  try { rmSync(path.join(temp, 'test.db'), { force: true }) } catch {}
}
