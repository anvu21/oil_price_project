import { useState, useEffect, useCallback } from 'react'
import StateMap from './components/StateMap.jsx'
import PriceChart from './components/PriceChart.jsx'
import PeriodToggle from './components/PeriodToggle.jsx'
import RangeToggle from './components/RangeToggle.jsx'
import {
  fetchLatestPrices,
  fetchStatePrices,
  fetchNationalPrices,
} from './api/client.js'

/**
 * Convert a range key ('1Y', '2Y', '3Y', 'all') to an ISO date string
 * suitable for the API's `from` query parameter, or null for "all time".
 */
function getRangeFromDate(range) {
  if (range === 'all') return null
  const years = parseInt(range)   // '1Y' → 1, '3Y' → 3
  const d = new Date()
  d.setFullYear(d.getFullYear() - years)
  return d.toISOString().slice(0, 10)  // YYYY-MM-DD
}

const STATE_NAMES = {
  AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California',
  CO: 'Colorado', CT: 'Connecticut', DE: 'Delaware', DC: 'District of Columbia',
  FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois',
  IN: 'Indiana', IA: 'Iowa', KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana',
  ME: 'Maine', MD: 'Maryland', MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota',
  MS: 'Mississippi', MO: 'Missouri', MT: 'Montana', NE: 'Nebraska', NV: 'Nevada',
  NH: 'New Hampshire', NJ: 'New Jersey', NM: 'New Mexico', NY: 'New York',
  NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio', OK: 'Oklahoma', OR: 'Oregon',
  PA: 'Pennsylvania', RI: 'Rhode Island', SC: 'South Carolina', SD: 'South Dakota',
  TN: 'Tennessee', TX: 'Texas', UT: 'Utah', VT: 'Vermont', VA: 'Virginia',
  WA: 'Washington', WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming',
}

function Spinner() {
  return (
    <div className="flex items-center justify-center py-20">
      <div className="w-8 h-8 border-2 border-blue-700 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

function formatPrice(p) {
  return p != null ? `$${Number(p).toFixed(3)}` : '—'
}

export default function App() {
  // 'map' = choropleth view, 'state' = drill-down chart view
  const [view, setView] = useState('map')

  const [latestPrices, setLatestPrices]   = useState(null)
  const [weekStart, setWeekStart]         = useState(null)
  const [nationalAvg, setNationalAvg]     = useState(null)

  const [selectedState, setSelectedState] = useState(null)
  const [period, setPeriod]               = useState('weekly')
  const [range, setRange]                 = useState('3Y')
  const [stateData, setStateData]         = useState(null)
  const [nationalData, setNationalData]   = useState(null)
  const [stateNoData, setStateNoData]     = useState(false)
  const [stateSource, setStateSource]     = useState(null) // { source, region_name }

  const [mapLoading, setMapLoading]       = useState(true)
  const [chartLoading, setChartLoading]   = useState(false)

  // ── Load map data on mount ───────────────────────────────────────────────
  useEffect(() => {
    setMapLoading(true)
    Promise.all([
      fetchLatestPrices(),
      fetchNationalPrices('weekly'),
    ])
      .then(([latest, national]) => {
        setLatestPrices(latest.data || [])
        setWeekStart(latest.week_start || null)

        // Most recent national average (last entry, sorted ascending from API)
        const nd = national.data || []
        if (nd.length > 0) setNationalAvg(nd[nd.length - 1].avg_price)
      })
      .finally(() => setMapLoading(false))
  }, [])

  // ── Load national series when period or range changes (for chart overlay) ──
  useEffect(() => {
    fetchNationalPrices(period, getRangeFromDate(range))
      .then((res) => setNationalData(res.data || []))
      .catch(() => setNationalData([]))
  }, [period, range])

  // ── Load state series when state, period, or range changes ─────────────
  const loadStateData = useCallback((state, per, rng) => {
    if (!state) return
    setChartLoading(true)
    setStateNoData(false)
    fetchStatePrices(state, per, 'regular', getRangeFromDate(rng))
      .then((res) => {
        setStateData(res.data || [])
        setStateSource({
          source:      res.source || 'state',
          region_name: res.region_name || null,
        })
      })
      .catch((err) => {
        setStateData([])
        setStateSource(null)
        if (err.message?.includes('404')) setStateNoData(true)
      })
      .finally(() => setChartLoading(false))
  }, [])

  useEffect(() => {
    if (selectedState) loadStateData(selectedState, period, range)
  }, [selectedState, period, range, loadStateData])

  // ── Handlers ─────────────────────────────────────────────────────────────
  const handleStateSelect = (abbr) => {
    setSelectedState(abbr)
    setStateData(null)
    setStateNoData(false)
    setStateSource(null)
    setView('state')
  }

  const handleBack = () => {
    setView('map')
  }

  const stateName = selectedState ? (STATE_NAMES[selectedState] || selectedState) : ''

  // ═══════════════════════════════════════════════════════════════════════════
  // MAP VIEW
  // ═══════════════════════════════════════════════════════════════════════════
  if (view === 'map') {
    return (
      <div className="min-h-screen bg-gray-100 flex flex-col">
        {/* Header */}
        <header className="bg-slate-900 text-white px-6 py-4 shadow">
          <div className="max-w-6xl mx-auto">
            <h1 className="text-2xl font-bold tracking-tight">US Gas Price Dashboard</h1>
            <p className="text-slate-400 text-sm mt-0.5">
              Weekly retail regular gasoline · click a state to view history
            </p>
          </div>
        </header>

        {/* Map card */}
        <main className="flex-1 max-w-6xl mx-auto w-full px-4 py-6">
          <div className="bg-white rounded-2xl shadow-md overflow-hidden">
            {/* Card header */}
            <div className="px-6 pt-5 pb-2 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
              <div>
                <h2 className="text-lg font-semibold text-gray-800">
                  National Retail Gas Prices
                </h2>
                {weekStart && (
                  <p className="text-xs text-gray-500 mt-0.5">
                    Price as of {weekStart}
                  </p>
                )}
              </div>
            </div>

            {/* No-data banner */}
            {!mapLoading && latestPrices && latestPrices.length === 0 && (
              <div className="mx-4 mb-2 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-800">
                <p className="font-semibold">No price data in the local database.</p>
                <p className="mt-0.5 text-amber-700">
                  Seed it by running the backfill script or inserting rows manually —
                  see <span className="font-mono">README.md → Seed local data</span>.
                </p>
              </div>
            )}

            {/* Map */}
            <div className="px-4 pb-2">
              {mapLoading ? (
                <Spinner />
              ) : (
                <StateMap
                  prices={latestPrices}
                  selectedState={null}
                  onStateSelect={handleStateSelect}
                />
              )}
            </div>

            {/* National average bar */}
            {!mapLoading && (
              <div className="border-t border-gray-100 px-6 py-4 bg-gray-50 flex items-center justify-center gap-3">
                <div className="flex items-center gap-4">
                  <div className="text-center">
                    <p className="text-xs uppercase tracking-widest text-gray-500 font-medium">
                      National Average
                    </p>
                    <p className="text-3xl font-bold text-slate-800 mt-0.5">
                      {formatPrice(nationalAvg)}
                      <span className="text-sm font-normal text-gray-500 ml-1">/gal</span>
                    </p>
                    {weekStart && (
                      <p className="text-xs text-gray-400 mt-0.5">as of {weekStart}</p>
                    )}
                  </div>
                  <div className="hidden sm:block h-12 w-px bg-gray-200" />
                  <p className="hidden sm:block text-sm text-gray-500 max-w-xs">
                    Click any state to see its weekly, monthly, and yearly price history.
                  </p>
                </div>
              </div>
            )}
          </div>
        </main>

        <footer className="text-center text-xs text-gray-400 py-4">
          Data source: EIA Open Data API · Updated weekly every Monday
        </footer>
      </div>
    )
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // STATE DETAIL VIEW
  // ═══════════════════════════════════════════════════════════════════════════
  return (
    <div className="min-h-screen bg-gray-100 flex flex-col">
      {/* Header */}
      <header className="bg-slate-900 text-white px-6 py-4 shadow">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="flex items-center gap-4">
            <button
              onClick={handleBack}
              className="flex items-center gap-1.5 text-slate-300 hover:text-white transition-colors text-sm font-medium"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
              All States
            </button>
            <div className="h-5 w-px bg-slate-700" />
            <div>
              <h1 className="text-xl font-bold">{stateName}</h1>
              <p className="text-slate-400 text-xs mt-0.5">Regular grade · {period}</p>
              {stateSource?.source === 'region' && stateSource?.region_name && (
                <p className="text-amber-400 text-xs mt-0.5">
                  Regional avg — {stateSource.region_name}
                </p>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <RangeToggle range={range} onChange={setRange} />
            <div className="hidden sm:block h-5 w-px bg-slate-700" />
            <PeriodToggle period={period} onChange={setPeriod} />
          </div>
        </div>
      </header>

      {/* Chart card */}
      <main className="flex-1 max-w-6xl mx-auto w-full px-4 py-6">
        <div className="bg-white rounded-2xl shadow-md p-6">
          {/* State summary row */}
          {stateData && stateData.length > 0 && (() => {
            const latest = stateData[stateData.length - 1]
            const oldest = stateData[0]
            const change = latest.avg_price - oldest.avg_price
            const isUp = change >= 0
            return (
              <div className="flex flex-wrap gap-6 mb-6 pb-6 border-b border-gray-100">
                <div>
                  <p className="text-xs uppercase tracking-widest text-gray-500 font-medium">
                    Latest Price
                  </p>
                  <p className="text-3xl font-bold text-slate-800 mt-0.5">
                    {formatPrice(latest.avg_price)}
                    <span className="text-sm font-normal text-gray-500 ml-1">/gal</span>
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">{latest.date}</p>
                </div>
                <div className="h-12 w-px bg-gray-200 self-center hidden sm:block" />
                <div>
                  <p className="text-xs uppercase tracking-widest text-gray-500 font-medium">
                    Change ({range === 'all' ? 'all time' : range})
                  </p>
                  <p className={`text-2xl font-semibold mt-0.5 ${isUp ? 'text-red-600' : 'text-blue-700'}`}>
                    {isUp ? '▲' : '▼'} {formatPrice(Math.abs(change))}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    from {oldest.date}
                  </p>
                </div>
                <div className="h-12 w-px bg-gray-200 self-center hidden sm:block" />
                <div>
                  <p className="text-xs uppercase tracking-widest text-gray-500 font-medium">
                    National Avg (latest)
                  </p>
                  <p className="text-2xl font-semibold text-gray-600 mt-0.5">
                    {nationalAvg != null ? formatPrice(nationalAvg) : '—'}
                    <span className="text-sm font-normal text-gray-400 ml-1">/gal</span>
                  </p>
                </div>
              </div>
            )
          })()}

          {/* Chart */}
          {chartLoading ? (
            <Spinner />
          ) : stateNoData ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <p className="text-4xl mb-3">📭</p>
              <p className="text-gray-700 font-semibold">No EIA data for {stateName}</p>
              <p className="text-gray-400 text-sm mt-1">
                The EIA does not publish weekly retail prices for all states.
              </p>
              <button
                onClick={handleBack}
                className="mt-5 text-sm text-blue-600 hover:text-blue-800 underline"
              >
                ← Back to map
              </button>
            </div>
          ) : (
            <PriceChart
              stateData={stateData}
              nationalData={nationalData}
              stateName={stateName}
              period={period}
            />
          )}
        </div>
      </main>

      <footer className="text-center text-xs text-gray-400 py-4">
        Data source: EIA Open Data API · Updated weekly every Monday
      </footer>
    </div>
  )
}
