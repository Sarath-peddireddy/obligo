import { useEffect, useRef, useState } from 'react'
import { Check, Copy, ExternalLink, KeyRound, Link2, X } from 'lucide-react'
import { request } from './api'

const prompt = `Create a contract in Obligo for Acme Cloud Services.

Contract title: Annual Software Agreement
Renewal date: 2027-03-15
Cancellation notice: 30 days

Add an obligation:
Title: Review cancellation deadline
Description: Decide whether to renew or cancel the vendor agreement.
Due date: 2027-02-13
Owner: Finance Manager

Use the Obligo MCP tools to save this information.`
type Info = { mcp_url: string | null; guest: boolean }

export default function ConnectGuide({ onClose }: { onClose: () => void; onContracts: () => void }) {
  const [info, setInfo] = useState<Info | null>(null); const [error, setError] = useState(''); const [token, setToken] = useState(''); const [busy, setBusy] = useState(false); const [copied, setCopied] = useState('')
  const dialog = useRef<HTMLDivElement>(null)
  useEffect(() => { let active = true; request<Info>('/api/session/connection').then(v => { if (active) setInfo(v) }).catch(() => { if (active) setError('Could not load connection settings. Please try again.') }); return () => { active = false } }, [])
  useEffect(() => { const previous = document.activeElement as HTMLElement | null; dialog.current?.focus(); const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); if (e.key === 'Tab' && dialog.current) { const items = [...dialog.current.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input:not([disabled]),textarea:not([disabled])')]; if (!items.length) return; if (e.shiftKey && document.activeElement === items[0]) { e.preventDefault(); items[items.length - 1].focus() } else if (!e.shiftKey && document.activeElement === items[items.length - 1]) { e.preventDefault(); items[0].focus() } } }; document.addEventListener('keydown', key); return () => { document.removeEventListener('keydown', key); previous?.focus() } }, [onClose])
  async function copy(text: string, label: string) { try { await navigator.clipboard.writeText(text); setCopied(label); setError('') } catch { setError('Could not copy. Please select the text and copy it manually.') } }
  async function createToken() { setBusy(true); setError(''); try { const result = await request<{ token: string }>('/api/session/mcp-token', { method: 'POST', body: {} }); setToken(result.token) } catch { setError('Could not create a guest credential. Please try again.') } finally { setBusy(false) } }
  return <div className="guide-overlay"><div className="guide-dialog" role="dialog" aria-modal="true" aria-labelledby="guide-title" aria-describedby="guide-subtitle" tabIndex={-1} ref={dialog}><header className="guide-header"><div><span className="guide-kicker"><Link2 size={14} /> CLAUDE CONNECTION</span><h2 id="guide-title">Connect Claude</h2><p id="guide-subtitle">Connect your Claude account to create contracts in Obligo.</p></div><button className="icon-btn" aria-label="Close connection guide" onClick={onClose}><X size={20} /></button></header><div className="guide-body">
    <section className="guide-step"><span className="guide-number">1</span><div><h3>Open Claude</h3><p>Sign in to your Claude account in a new tab.</p><a className="btn btn-secondary guide-link" href="https://claude.ai" target="_blank" rel="noopener noreferrer">Open Claude <ExternalLink size={14} /></a></div></section>
    <section className="guide-step"><span className="guide-number">2</span><div><h3>Add a custom connector</h3><p>In Claude, go to <strong>Customize → Connectors → Add → Custom → Web</strong>. This lets Claude use tools provided by Obligo.</p></div></section>
    <section className="guide-step"><span className="guide-number">3</span><div><h3>Enter the Obligo server URL</h3>{!info && !error ? <p>Loading connection settings…</p> : info?.mcp_url ? <div className="copy-row"><code>{info.mcp_url}</code><button className="btn btn-secondary" onClick={() => void copy(info.mcp_url!, 'url')}><Copy size={14} /> Copy URL</button></div> : <p className="guide-warning">MCP endpoint not configured yet.</p>}</div></section>
    <section className="guide-step"><span className="guide-number">4</span><div><h3>Set up your guest credential</h3><p>In Claude, choose <strong>No sign in</strong> if prompted. Under <strong>Request headers</strong>, enter the name <code>Authorization</code> and paste the complete value from <strong>Copy header</strong>. It begins with <code>Bearer </code> and only accesses this guest workspace.</p>{info?.guest ? <>{!token ? <button className="btn btn-secondary" disabled={busy} onClick={() => void createToken()}><KeyRound size={14} /> {busy ? 'Creating…' : 'Create guest credential'}</button> : <><div className="copy-row"><input aria-label="Guest authorization header" readOnly value={`Bearer ${token}`} /><button className="btn btn-secondary" onClick={() => void copy(`Bearer ${token}`, 'credential')}><Copy size={14} /> Copy header</button></div><p className="guide-note">Use this guest credential, not the token in backend/.env. Treat it like a password. It expires with your guest session and is revoked at sign-out. Creating a new credential replaces the old one.</p></>}</> : info && <p className="guide-warning">Guest credentials require a guest session. This guide never displays the workspace's master token.</p>}</div></section>
    <section className="guide-step"><span className="guide-number">5</span><div><h3>Save the connector</h3><p>Finish adding the connector and enable these tools if Claude asks:</p><div className="tool-list"><code>create_contract</code><code>add_obligation</code><code>list_contracts</code><code>list_obligations</code></div><p className="guide-note">Connection status is not verified by Obligo.</p></div></section>
    <section className="guide-step"><span className="guide-number">6</span><div><h3>Try a sample prompt</h3><p>These are fictional demonstration details.</p><pre>{prompt}</pre><button className="btn btn-secondary" onClick={() => void copy(prompt, 'prompt')}><Copy size={14} /> Copy prompt</button></div></section>

    {error && <div className="guide-feedback error" role="alert">{error}</div>}{copied && <div className="guide-feedback" role="status"><Check size={14} /> {copied === 'url' ? 'URL' : copied === 'credential' ? 'Header' : 'Prompt'} copied.</div>}
  </div></div></div>
}
