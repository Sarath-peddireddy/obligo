// Generate a Vercel rewrite only after the real HTTPS backend origin is known.
import { readFileSync, writeFileSync } from 'node:fs'

const raw = process.env.BACKEND_ORIGIN
let url
try { url = new URL(raw) } catch { throw new Error('Set BACKEND_ORIGIN to your actual HTTPS backend origin') }
if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
  throw new Error('BACKEND_ORIGIN must be an HTTPS origin without credentials, path, query, or fragment')
}
const config = JSON.parse(readFileSync('vercel.json', 'utf8'))
if (!Array.isArray(config.rewrites) || config.rewrites.some(rule => rule.source === '/api/:path*')) {
  throw new Error('Review vercel.json: rewrites must exist and must not already contain an API rewrite')
}
config.rewrites.unshift({ source: '/api/:path*', destination: `${url.origin}/api/:path*` })
writeFileSync('vercel.json', JSON.stringify(config, null, 2) + '\n')
console.log('Added an API rewrite to vercel.json; review it before deploying.')
