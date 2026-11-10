import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backend = process.env.OBLIGO_PROXY_TARGET || 'http://127.0.0.1:8000'
export default defineConfig({ plugins: [react()], server: { proxy: { '/api': backend, '/mcp': backend } } })
