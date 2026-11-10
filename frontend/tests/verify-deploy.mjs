// Read-only public deployment checks. Never prints credentials.
import { chromium } from 'playwright'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

const url = process.argv[2]
if (!url || new URL(url).protocol !== 'https:') throw new Error('Provide the deployed HTTPS origin')
const root = await fetch(url)
if (root.status !== 200) throw new Error(`Frontend returned HTTP ${root.status}`)
const html = await root.text()
const paths = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map(match => match[1])
if (paths.length < 2) throw new Error('Expected JavaScript and CSS assets in the frontend HTML')
let served = html
for (const asset of paths) {
  const response = await fetch(new URL(asset, url))
  if (response.status !== 200) throw new Error(`Asset failed: ${asset}`)
  served += await response.text()
}
const route = await fetch(new URL('/contracts', url))
if (route.status !== 200 || !(await route.text()).includes('<div id="root">')) throw new Error('Direct client-side route did not serve the app')
for (const name of ['../backend/.env', '.env.local']) {
  if (!existsSync(name)) continue
  for (const line of readFileSync(name, 'utf8').split(/\r?\n/)) {
    const match = line.match(/^(?:MCP_BEARER_TOKEN|VERCEL_OIDC_TOKEN)=(.+)$/)
    const secret = match?.[1].replace(/^['"]|['"]$/g, '')
    if (secret && secret.length >= 16 && served.includes(secret)) throw new Error('A local secret was found in the served assets')
  }
}
const executablePath = process.env.CHROME_PATH || (process.platform === 'win32' ? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' : undefined)
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
try {
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(new URL('/contracts#/obligations', url).href, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Clarity starts here.' }).waitFor()
  await page.getByText('Backend connection is pending.', { exact: false }).waitFor()
  if (await page.getByRole('button', { name: /sign in to workspace/i }).isEnabled()) throw new Error('Frontend-only sign-in should be disabled')
  if (new URL(page.url()).hash !== '#/obligations' || errors.length) throw new Error('Client-side route or browser runtime failed')
  console.log('PASS: public HTTPS 200, JS/CSS assets, direct route, browser rendering, frontend-only state, and known-secret scan.')
} finally { await browser.close() }
