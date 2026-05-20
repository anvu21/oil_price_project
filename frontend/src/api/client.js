const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function apiFetch(path) {
  const url = `${BASE}${path}`
  console.debug(`[API] GET ${url}`)
  const res = await fetch(url)
  if (!res.ok) {
    console.error(`[API] ${res.status} ${res.statusText} — ${url}`)
    throw new Error(`API error ${res.status}: ${res.statusText}`)
  }
  const data = await res.json()
  console.debug(`[API] response`, data)
  return data
}

/**
 * Fetch the latest weekly gas prices for all states.
 * Returns: { week_start: "2026-03-23", data: [{state, avg_price, week_start}, ...] }
 */
export async function fetchLatestPrices() {
  return apiFetch('/v1/prices/latest')
}

/**
 * Fetch price history for a specific state.
 * Returns: { state, period, grade, source, region_name, data: [{date, avg_price}, ...] }
 * @param {string|null} from  ISO date string (YYYY-MM-DD) for the start of the range, or null for all
 */
export async function fetchStatePrices(state, period = 'weekly', grade = 'regular', from = null) {
  const params = new URLSearchParams({ period, grade })
  if (from) params.set('from', from)
  return apiFetch(`/v1/prices/${state}?${params}`)
}

/**
 * Fetch national average price history.
 * Returns: { period, grade, data: [{date, avg_price}, ...] }
 * @param {string|null} from  ISO date string (YYYY-MM-DD) for the start of the range, or null for all
 */
export async function fetchNationalPrices(period = 'weekly', from = null) {
  const params = new URLSearchParams({ period })
  if (from) params.set('from', from)
  return apiFetch(`/v1/prices/national?${params}`)
}

/**
 * Fetch price history for multiple states side-by-side.
 * Returns: { period, grade, states: { CA: [{date, avg_price}], TX: [...], ... } }
 * @param {string[]} states  Array of state abbreviations, e.g. ['CA', 'TX', 'FL']
 * @param {string|null} from ISO date string or null for all history
 */
export async function fetchComparePrices(states, period = 'weekly', grade = 'regular', from = null) {
  const params = new URLSearchParams({ period, grade, states: states.join(',') })
  if (from) params.set('from', from)
  return apiFetch(`/v1/prices/compare?${params}`)
}
