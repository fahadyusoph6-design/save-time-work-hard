const TOKEN_KEY = 'stwh_token'

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch { /* storage unavailable */ }
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

export async function api(path, { method = 'GET', body, blob = false } = {}) {
  const headers = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let message = res.statusText
    try {
      const j = await res.json()
      message = typeof j.detail === 'string' ? j.detail : (j.detail || []).map((d) => d.msg).join('; ')
    } catch { /* not json */ }
    if (res.status === 401 && path !== '/auth/login') window.dispatchEvent(new Event('stwh-logout'))
    throw new ApiError(res.status, message)
  }
  return blob ? res.blob() : res.json()
}

/** Sends a File as the raw request body (no multipart), returns parsed JSON. */
export async function uploadFile(path, file) {
  const headers = { 'Content-Type': 'application/octet-stream' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`/api${path}`, { method: 'POST', headers, body: file })
  if (!res.ok) {
    let message = res.statusText
    try { message = (await res.json()).detail || message } catch { /* not json */ }
    if (res.status === 401) window.dispatchEvent(new Event('stwh-logout'))
    throw new ApiError(res.status, message)
  }
  return res.json()
}

export function qs(params) {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== '' && v !== null && v !== undefined) p.set(k, v)
  })
  const s = p.toString()
  return s ? `?${s}` : ''
}

export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

const pad = (n) => String(n).padStart(2, '0')

export function localDate(d = new Date()) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function localTime(d = new Date()) {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function dirname(path) {
  const i = Math.max(path.lastIndexOf('\\'), path.lastIndexOf('/'))
  return i >= 0 ? path.slice(0, i) : path
}

export function cleanFilename(name) {
  return name.replace(/[<>:"/\\|?*\x00-\x1f]/g, '').replace(/\s+/g, ' ').trim()
}

export const KNOWN_JOBSITES = [
  'LinkedIn', 'Indeed', 'Glassdoor', 'ZipRecruiter', 'Dice', 'Monster', 'Upwork', 'Wellfound',
  'Greenhouse', 'Lever', 'Workday', 'Ashby', 'SmartRecruiters', 'Built In', 'Company website',
]

/** Strips scripts and event handlers from stored HTML before it goes back into the editor. */
export function sanitizeHtml(html) {
  const doc = new DOMParser().parseFromString(html || '', 'text/html')
  doc.querySelectorAll('script, iframe, object, embed, link, meta, base, form').forEach((el) => el.remove())
  doc.querySelectorAll('*').forEach((el) => {
    [...el.attributes].forEach((a) => {
      if (/^on/i.test(a.name) || /^\s*javascript:/i.test(a.value)) el.removeAttribute(a.name)
    })
  })
  return doc.body.innerHTML
}
