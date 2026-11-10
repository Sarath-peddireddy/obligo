export type Contract = { id: number; vendor_name: string; title: string; renewal_date: string | null; notice_period_days: number | null; source_clause: string | null }
export type Obligation = { id: number; contract_id: number; title: string; description: string | null; due_date: string | null; owner: string | null; source_clause: string | null; review_status: string; is_completed: boolean; status: string }
export type Summary = { total_contracts: number; total_obligations: number; pending_review_count: number; overdue_count: number; due_today_count: number; due_soon_count: number; completed_count: number }

const base = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
export const frontendOnly = import.meta.env.VITE_FRONTEND_ONLY === 'true'
export const apiBase = base || 'Same origin (development proxy)'
let csrfToken = ''
export function setCsrfToken(value: string) { csrfToken = value }

export class ApiError extends Error { constructor(public status: number, message: string) { super(message) } }

export async function request<T>(path: string, options: { method?: string; body?: unknown; login?: boolean } = {}): Promise<T> {
  const method = options.method || 'GET'
  const headers: Record<string, string> = {}
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (!options.login && method !== 'GET') headers['X-CSRF-Token'] = csrfToken
  let response: Response
  try { response = await fetch(`${base}${path}`, { method, headers, credentials: 'include', body: options.body === undefined ? undefined : JSON.stringify(options.body) }) }
  catch { throw new ApiError(0, 'Could not reach the backend. Check your connection and try again.') }
  if (!response.ok) {
    if (response.status === 401 && !options.login) window.dispatchEvent(new Event('obligo:expired'))
    let message = response.status === 401 ? 'Your session has expired. Please sign in again.' : 'Something went wrong. Please try again.'
    if (options.login && response.status === 401) message = 'That workspace token was not recognized.'
    if (response.status === 422) message = 'Check the fields and try again.'
    if (response.status === 404) message = 'This record could not be found.'
    if (response.status === 409) message = 'Approve this obligation before completing it.'
    if (response.status === 429) message = 'Guest sign-in limit reached. Please try again later.'
    if (response.status === 403) message = 'Your session could not authorize this action. Please sign in again.'
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}

export function formatDate(value: string | null): string {
  if (!value) return 'Not set'
  const [year, month, day] = value.split('-').map(Number)
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month - 1, day)))
}
