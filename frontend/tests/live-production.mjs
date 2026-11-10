// Public end-to-end check. Guest credentials remain in memory and are sent to the MCP client over stdin.
import { chromium } from 'playwright'
import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const backend = path.resolve(frontend, '..', 'backend')
const python = process.platform === 'win32' ? path.join(backend, '.venv', 'Scripts', 'python.exe') : path.join(backend, '.venv', 'bin', 'python')
const chrome = process.env.CHROME_PATH || (process.platform === 'win32' ? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' : undefined)
const frontendUrl = 'https://obligo-workspace.vercel.app'
const mcpUrl = 'https://obligo-workspace-api.vercel.app/mcp'
const marker = 'obligo-browser-test-' + randomBytes(12).toString('hex')
console.log('Disposable record marker:', marker)
function assert(value, message) { if (!value) throw new Error(message) }
function createRecords(token) {
  return new Promise((resolve, reject) => {
    const process = spawn(python, [path.join(backend, 'tests', 'live_mcp_client.py')], { cwd: backend, stdio: ['pipe', 'pipe', 'pipe'] })
    let out = '', err = ''
    process.stdout.on('data', chunk => { out += chunk })
    process.stderr.on('data', chunk => { err += chunk })
    process.on('error', reject)
    process.on('close', code => { if (code) reject(new Error('MCP client failed: ' + err)); else { try { resolve(JSON.parse(out)) } catch { reject(new Error('Invalid MCP client result')) } } })
    process.stdin.end(JSON.stringify({ token, url: mcpUrl, marker }))
  })
}
const browser = await chromium.launch({ headless: true, ...(chrome ? { executablePath: chrome } : {}) })
try {
  const contextA = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const contextB = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const a = await contextA.newPage(), b = await contextB.newPage()
  await Promise.all([a.goto(frontendUrl), b.goto(frontendUrl)])
  await a.getByRole('button', { name: 'Continue as Guest' }).click()
  await a.getByRole('heading', { name: 'No contracts yet' }).waitFor({ timeout: 60000 })
  await b.getByRole('button', { name: 'Continue as Guest' }).click()
  await b.getByRole('heading', { name: 'No contracts yet' }).waitFor({ timeout: 60000 })
  const cookies = await contextA.cookies()
  const session = cookies.find(cookie => cookie.name === 'obligo_session')
  assert(session?.httpOnly && session.secure && session.sameSite === 'Strict', 'Session cookie security attributes were not preserved')
  await a.reload()
  await a.getByRole('heading', { name: 'Overview', exact: true }).waitFor({ timeout: 60000 })
  console.log('Guest sign-in and session persistence: PASS')
  await a.getByRole('button', { name: 'Connect Claude' }).first().click()
  await a.getByText(mcpUrl, { exact: true }).waitFor({ timeout: 60000 })
  await a.getByRole('button', { name: 'Create guest credential' }).click()
  const header = await a.getByLabel('Guest authorization header').inputValue({ timeout: 60000 })
  assert(header.startsWith('Bearer '), 'Guest credential was not issued')
  const token = header.slice(7)
  const result = await createRecords(token)
  console.log('Public MCP discovery, creation, and independent reconnection: PASS')
  await a.getByRole('button', { name: 'Close connection guide' }).click()
  await a.getByRole('button', { name: 'Contracts', exact: true }).click()
  await a.getByRole('button', { name: new RegExp(marker) }).first().waitFor({ timeout: 60000 })
  assert(await b.evaluate(async id => (await fetch(`/api/contracts/${id}`, { credentials: 'include' })).status, result.contract_id) === 404, 'Guest B accessed Guest A contract')
  assert(await b.evaluate(async id => (await fetch(`/api/obligations/${id}`, { credentials: 'include' })).status, result.obligation_id) === 404, 'Guest B accessed Guest A obligation')
  await b.getByRole('button', { name: 'Contracts', exact: true }).click()
  await b.getByText('No contracts yet').waitFor({ timeout: 60000 })
  console.log('Two guest workspaces and cross-workspace isolation: PASS')
  await a.getByRole('button', { name: 'Obligations', exact: true }).click()
  await a.locator('.table-link').filter({ hasText: marker }).click({ timeout: 60000 })
  await a.getByRole('button', { name: 'Edit obligation' }).click()
  await a.getByLabel('Description').fill('Verified persistent browser edit')
  await a.getByRole('button', { name: 'Save changes' }).click()
  await a.getByText('Obligation updated successfully.').waitFor({ timeout: 60000 })
  await a.reload()
  await a.getByText('Verified persistent browser edit', { exact: true }).waitFor({ timeout: 60000 })
  console.log('Browser edit and reload persistence: PASS')
  await a.locator('summary').click()
  await a.getByRole('button', { name: 'Sign out' }).click()
  await a.getByRole('button', { name: 'Continue as Guest' }).waitFor()
  const revoked = await fetch(mcpUrl, { method: 'POST', headers: { Authorization: header } })
  assert(revoked.status === 401, 'Revoked guest credential still works')
  console.log('Guest sign-out and MCP revocation: PASS')
  await contextA.close(); await contextB.close()
} catch (error) {
  console.error('Public browser test failed:', error.message)
  process.exitCode = 1
} finally { await browser.close() }
