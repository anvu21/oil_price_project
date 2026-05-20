import { useState, useEffect, useCallback } from 'react'
import StateMap from './components/StateMap.jsx'
import PriceChart, { STATE_COLORS } from './components/PriceChart.jsx'
import PeriodToggle from './components/PeriodToggle.jsx'
import RangeToggle from './components/RangeToggle.jsx'
import {
  fetchLatestPrices,
  fetchStatePrices,
  fetchNationalPrices,
  fetchComparePrices,
} from './api/client.js'

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Convert a range key ('1', '5', '10', 'all') to an ISO start-date string
 * for the API's `from` query parameter, or null for "all time".
 */
function getRangeFromDate(range) {
  if (range === 'all') return null
  const years = parseInt(range, 10)   // '1' → 1, '10' → 10
  const d = new Date()
  d.setFullYear(d.getFullYear() - years)
  return d.toISOString().slice(0, 10)
}

/** Human-readable label for the current range, e.g. "5Y" or "all time". */
function rangeLabel(range) {
  return range === 'all' ? 'all time' : `${range}Y`
}

const STATE_NAMES = {
  AL:'Alabama', AK:'Alaska', AZ:'Arizona', AR:'Arkansas', CA:'California',
  CO:'Colorado', CT:'Connecticut', DE:'Delaware', DC:'District of Columbia',
  FL:'Florida', GA:'Georgia', HI:'Hawaii', ID:'Idaho', IL:'Illinois',
  IN:'Indiana', IA:'Iowa', KS:'Kansas', KY:'Kentucky', LA:'Louisiana',
  ME:'Maine', MD:'Maryland', MA:'Massachusetts', MI:'Michigan', MN:'Minnesota',
  MS:'Mississippi', MO:'Missouri', MT:'Montana', NE:'Nebraska', NV:'Nevada',
  NH:'New Hampshire', NJ:'New Jersey', NM:'New Mexico', NY:'New York',
  NC:'North Carolina', ND:'North Dakota', OH:'Ohio', OK:'Oklahoma', OR:'Oregon',
  PA:'Pennsylvania', RI:'Rhode Island', SC:'South Carolina', SD:'South Dakota',
  TN:'Tennessee', TX:'Texas', UT:'Utah', VT:'Vermont', VA:'Virginia',
  WA:'Washington', WV:'West Virginia', WI:'Wisconsin', WY:'Wyoming',
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

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  // 'map' → choropleth, 'detail' → chart (single or compare)
  const [view, setView] = useState('map')

  // Map data
  const [latestPrices, setLatestPrices]   = useState(null)
  const [weekStart, setWeekStart]         = useState(null)
  const [nationalAvg, setNationalAvg]     = useState(null)

  // Compare-mode on the map (staging states before navigating to detail view)
  const [compareMode, setCompareMode]     = useState(false)
  const [pendingCompare, setPendingCompare] = useState(new Set())

  // Chart / detail view state
  const [selectedStates, setSelectedStates] = useState([])  // 1 or more
  const [statesData, setStatesData]         = useState({})  // { abbr: [{date, avg_price}] }
  const [stateSource, setStateSource]       = useState(null) // single-state only
  const [nationalData, setNationalData]     = useState(null)
  const [period, setPeriod]                 = useState('weekly')
  const [range, setRange]                   = useState('3')
  const [chartLoading, setChartLoading]     = useState(false)
  const [stateNoData, setStateNoData]       = useState(false)

  const [mapLoading, setMapLoading]         = useState(true)

  // ── Load map data on mount ───────────────────────────────────────────────
  useEffect(() => {
    setMapLoading(true)
    Promise.all([fetchLatestPrices(), fetchNationalPrices('weekly')])
      .then(([latest, national]) => {
        setLatestPrices(latest.data || [])
        setWeekStart(latest.week_start || null)
        const nd = national.data || []
        if (nd.length) setNationalAvg(nd[nd.length - 1].avg_price)
      })
      .finally(() => setMapLoading(false))
  }, [])

  // ── National series for chart overlay ────────────────────────────────────
  useEffect(() => {
    if (view !== 'detail') return
    fetchNationalPrices(period, getRangeFromDate(range))
      .then((res) => setNationalData(res.data || []))
      .catch(() => setNationalData([]))
  }, [view, period, range])

  // ── Detail data: single state or compare ─────────────────────────────────
  const loadDetailData = useCallback(async (states, per, rng) => {
    if (!states.length) return
    setChartLoading(true)
    setStateNoData(false)
    setStateSource(null)

    try {
      const from = getRangeFromDate(rng)

      if (states.length === 1) {
        const res = await fetchStatePrices(states[0], per, 'regular', from)
        setStatesData({ [states[0]]: res.data || [] })
        setStateSource({
          source:      res.source || 'state',
          region_name: res.region_name || null,
        })
      } else {
        const res = await fetchComparePrices(states, per, 'regular', from)
        setStatesData(res.states || {})
      }
    } catch (err) {
      setStatesData({})
      if (err.message?.includes('404') || err.message?.includes('422'))
        setStateNoData(true)
    } finally {
      setChartLoading(false)
    }
  }, [])

  useEffect(() => {
    if (view === 'detail' && selectedStates.length) {
      loadDetailData(selectedStates, period, range)
    }
  }, [view, selectedStates, period, range, loadDetailData])

  // ── Map handlers ─────────────────────────────────────────────────────────
  const handleStateClick = (abbr) => {
    if (compareMode) {
      setPendingCompare((prev) => {
        const next = new Set(prev)
        if (next.has(abbr)) next.delete(abbr)
        else next.add(abbr)
        return next
      })
    } else {
      setSelectedStates([abbr])
      setStatesData({})
      setStateSource(null)
      setStateNoData(false)
      setView('detail')
    }
  }

  const handleStartCompare = () => {
    if (pendingCompare.size < 2) return
    setSelectedStates([...pendingCompare])
    setStatesData({})
    setStateSource(null)
    setStateNoData(false)
    setCompareMode(false)
    setPendingCompare(new Set())
    setView('detail')
  }

  const handleToggleCompareMode = () => {
    setCompareMode((prev) => !prev)
    setPendingCompare(new Set())
  }

  // ── Detail view handlers ──────────────────────────────────────────────────
  const handleBack = () => {
    setView('map')
    setSelectedStates([])
    setStatesData({})
    setStateSource(null)
  }

  /** Remove a state from the compare set in the detail view. */
  const handleRemoveState = (abbr) => {
    const next = selectedStates.filter((s) => s !== abbr)
    if (!next.length) {
      handleBack()
    } else {
      setSelectedStates(next)
    }
  }

  const isCompareView = selectedStates.length > 1

  // ═══════════════════════════════════════════════════════════════════════════
  // MAP VIEW
  // ═══════════════════════════════════════════════════════════════════════════
  if (view === 'map') {
    return (
      <div className="min-h-screen bg-gray-100 flex flex-col">
        <header className="bg-slate-900 text-white px-4 sm:px-6 py-3 sm:py-4 shadow">
          <div className="max-w-6xl mx-auto flex items-center justify-between gap-2">
            <div className="min-w-0">
              <h1 className="text-lg sm:text-2xl font-bold tracking-tight truncate">US Gas Price Dashboard</h1>
              <p className="text-slate-400 text-xs sm:text-sm mt-0.5 hidden sm:block">
                {compareMode
                  ? 'Compare mode: click states to add, then hit Compare'
                  : 'Weekly retail regular gasoline · click a state for history'}
              </p>
            </div>
            {/* Compare mode toggle */}
            <button
              onClick={handleToggleCompareMode}
              className={[
                'flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs sm:text-sm font-medium transition-colors whitespace-nowrap flex-shrink-0',
                compareMode
                  ? 'bg-amber-500 text-white hover:bg-amber-600'
                  : 'bg-slate-700 text-slate-200 hover:bg-slate-600',
              ].join(' ')}
            >
              <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
              <span className="hidden xs:inline">{compareMode ? 'Cancel' : 'Compare'}</span>
              <span className="xs:hidden">{compareMode ? '✕' : '⇌'}</span>
            </button>
          </div>
        </header>

        <main className="flex-1 max-w-6xl mx-auto w-full px-2 sm:px-4 py-3 sm:py-6">
          <div className="bg-white rounded-xl sm:rounded-2xl shadow-md overflow-hidden">
            <div className="px-4 sm:px-6 pt-4 sm:pt-5 pb-1 sm:pb-2 flex items-center justify-between">
              <div>
                <h2 className="text-base sm:text-lg font-semibold text-gray-800">National Retail Gas Prices</h2>
                {weekStart && (
                  <p className="text-xs text-gray-500 mt-0.5">as of {weekStart}</p>
                )}
              </div>
            </div>

            {!mapLoading && latestPrices?.length === 0 && (
              <div className="mx-4 mb-2 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-800">
                <p className="font-semibold">No price data in the database.</p>
              </div>
            )}

            <div className="px-2 sm:px-4 pb-2">
              {mapLoading ? (
                <Spinner />
              ) : (
                <StateMap
                  prices={latestPrices}
                  selectedStates={[...pendingCompare]}
                  compareMode={compareMode}
                  onStateSelect={handleStateClick}
                />
              )}
            </div>

            {/* Compare action bar */}
            {compareMode && pendingCompare.size > 0 && (
              <div className="border-t border-amber-100 bg-amber-50 px-4 sm:px-6 py-3 flex flex-wrap items-center gap-2 sm:gap-3">
                <div className="flex flex-wrap gap-1.5 sm:gap-2 flex-1">
                  {[...pendingCompare].map((abbr, i) => (
                    <span
                      key={abbr}
                      className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold text-white"
                      style={{ backgroundColor: STATE_COLORS[i % STATE_COLORS.length] }}
                    >
                      {abbr}
                      <button
                        onClick={() => setPendingCompare((prev) => { const n = new Set(prev); n.delete(abbr); return n })}
                        className="hover:opacity-75 leading-none ml-0.5"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
                <button
                  onClick={handleStartCompare}
                  disabled={pendingCompare.size < 2}
                  className="px-3 sm:px-4 py-1.5 sm:py-2 rounded-lg text-xs sm:text-sm font-semibold bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
                >
                  Compare {pendingCompare.size} →
                </button>
              </div>
            )}

            {/* National average bar */}
            {!mapLoading && !compareMode && (
              <div className="border-t border-gray-100 px-4 sm:px-6 py-3 sm:py-4 bg-gray-50">
                <div className="flex items-center justify-between sm:justify-center sm:gap-8">
                  <div>
                    <p className="text-xs uppercase tracking-widest text-gray-500 font-medium">National Avg</p>
                    <p className="text-2xl sm:text-3xl font-bold text-slate-800 mt-0.5">
                      {formatPrice(nationalAvg)}
                      <span className="text-xs sm:text-sm font-normal text-gray-500 ml-1">/gal</span>
                    </p>
                    {weekStart && <p className="text-xs text-gray-400 mt-0.5">as of {weekStart}</p>}
                  </div>
                  <p className="text-xs sm:text-sm text-gray-400 max-w-[180px] sm:max-w-xs text-right sm:text-left">
                    Tap a state for price history, or compare multiple states.
                  </p>
                </div>
              </div>
            )}
          </div>
        </main>

        <footer className="text-center text-xs text-gray-400 py-3">
          Data: EIA Open Data API · Updated weekly
        </footer>
      </div>
    )
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // DETAIL VIEW  (single state  OR  multi-state comparison)
  // ═══════════════════════════════════════════════════════════════════════════
  const firstState  = selectedStates[0]
  const firstName   = firstState ? (STATE_NAMES[firstState] || firstState) : ''

  return (
    <div className="min-h-screen bg-gray-100 flex flex-col">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="bg-slate-900 text-white px-4 sm:px-6 py-3 sm:py-4 shadow">
        <div className="max-w-6xl mx-auto">
          {/* Top row: back + title + controls */}
          <div className="flex items-start sm:items-center justify-between gap-2">
            {/* Left: back + title */}
            <div className="flex items-center gap-3 min-w-0">
              <button
                onClick={handleBack}
                className="flex items-center gap-1 text-slate-300 hover:text-white transition-colors text-sm font-medium flex-shrink-0"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
                </svg>
                <span className="hidden sm:inline">All States</span>
              </button>
              <div className="h-5 w-px bg-slate-700 flex-shrink-0" />
              <div className="min-w-0">
                {isCompareView ? (
                  <>
                    <h1 className="text-base sm:text-xl font-bold">Comparison</h1>
                    <p className="text-slate-400 text-xs mt-0.5 hidden sm:block">
                      Regular · {period} · {rangeLabel(range)}
                    </p>
                  </>
                ) : (
                  <>
                    <h1 className="text-base sm:text-xl font-bold truncate">{firstName}</h1>
                    <p className="text-slate-400 text-xs mt-0.5 hidden sm:block">
                      Regular · {period}
                      {stateSource?.source === 'region' && stateSource?.region_name && (
                        <> · <span className="text-amber-400">Regional avg</span></>
                      )}
                    </p>
                  </>
                )}
              </div>
            </div>

            {/* Right: controls — stack on mobile */}
            <div className="flex flex-col sm:flex-row items-end sm:items-center gap-1.5 sm:gap-2 flex-shrink-0">
              <RangeToggle range={range} onChange={setRange} />
              <PeriodToggle period={period} onChange={setPeriod} />
            </div>
          </div>

          {/* State chips (compare view) */}
          {isCompareView && (
            <div className="mt-2 sm:mt-3 flex flex-wrap gap-1.5 sm:gap-2">
              {selectedStates.map((abbr, i) => (
                <span
                  key={abbr}
                  className="flex items-center gap-1 pl-2.5 pr-1.5 py-0.5 rounded-full text-xs font-semibold text-white"
                  style={{ backgroundColor: STATE_COLORS[i % STATE_COLORS.length] }}
                >
                  {STATE_NAMES[abbr] || abbr}
                  <button
                    onClick={() => handleRemoveState(abbr)}
                    className="w-3.5 h-3.5 flex items-center justify-center rounded-full hover:bg-white/20 transition-colors leading-none"
                    title={`Remove ${abbr}`}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      </header>

      {/* ── Chart card ──────────────────────────────────────────────────────── */}
      <main className="flex-1 max-w-6xl mx-auto w-full px-2 sm:px-4 py-3 sm:py-6">
        <div className="bg-white rounded-xl sm:rounded-2xl shadow-md p-3 sm:p-6">

          {/* Single-state stats row */}
          {!isCompareView && statesData[firstState]?.length > 0 && (() => {
            const data   = statesData[firstState]
            const latest = data[data.length - 1]
            const oldest = data[0]
            const change = latest.avg_price - oldest.avg_price
            const isUp   = change >= 0
            return (
              <div className="grid grid-cols-3 gap-2 sm:gap-6 mb-4 sm:mb-6 pb-4 sm:pb-6 border-b border-gray-100">
                <div>
                  <p className="text-xs uppercase tracking-widest text-gray-500 font-medium">Latest</p>
                  <p className="text-xl sm:text-3xl font-bold text-slate-800 mt-0.5">
                    {formatPrice(latest.avg_price)}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5 hidden sm:block">{latest.date}</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-widest text-gray-500 font-medium">
                    Change
                  </p>
                  <p className={`text-lg sm:text-2xl font-semibold mt-0.5 ${isUp ? 'text-red-600' : 'text-blue-700'}`}>
                    {isUp ? '▲' : '▼'} {formatPrice(Math.abs(change))}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5 hidden sm:block">{rangeLabel(range)}</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-widest text-gray-500 font-medium">Nat'l Avg</p>
                  <p className="text-lg sm:text-2xl font-semibold text-gray-600 mt-0.5">
                    {nationalAvg != null ? formatPrice(nationalAvg) : '—'}
                  </p>
                </div>
              </div>
            )
          })()}

          {/* Chart */}
          {chartLoading ? (
            <Spinner />
          ) : stateNoData ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <p className="text-4xl mb-3">📭</p>
              <p className="text-gray-700 font-semibold">No data found</p>
              <p className="text-gray-400 text-sm mt-1">Try a different period or range.</p>
              <button onClick={handleBack} className="mt-5 text-sm text-blue-600 hover:text-blue-800 underline">
                ← Back to map
              </button>
            </div>
          ) : (
            <PriceChart
              statesData={statesData}
              stateNames={STATE_NAMES}
              nationalData={nationalData}
              period={period}
            />
          )}
        </div>
      </main>

      <footer className="text-center text-xs text-gray-400 py-3">
        Data: EIA Open Data API · Updated weekly
      </footer>
    </div>
  )
}
