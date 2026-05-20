import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

// Color palette for state lines (first = primary blue, rest contrast well)
export const STATE_COLORS = [
  '#2563eb', // blue
  '#dc2626', // red
  '#16a34a', // green
  '#d97706', // amber
  '#7c3aed', // purple
  '#db2777', // pink
  '#0891b2', // cyan
  '#65a30d', // lime
]

function formatXAxisTick(dateStr, period) {
  if (!dateStr) return ''
  if (period === 'yearly')  return dateStr.slice(0, 4)
  if (period === 'monthly') return dateStr.slice(0, 7)
  return dateStr.slice(5)  // weekly → MM-DD
}

function formatPrice(value) {
  if (value == null) return ''
  return `$${Number(value).toFixed(3)}`
}

function CustomTooltip({ active, payload, label, period }) {
  if (!active || !payload || !payload.length) return null

  let displayDate = label
  if (period === 'yearly')  displayDate = label?.slice(0, 4)
  else if (period === 'monthly') displayDate = label?.slice(0, 7)

  return (
    <div className="bg-white border border-gray-200 rounded-md shadow-md px-3 py-2 text-sm min-w-[140px]">
      <p className="font-medium text-gray-700 mb-1">{displayDate}</p>
      {payload.map((entry) => (
        <p key={entry.name} style={{ color: entry.color }} className="text-xs">
          {entry.name}: {formatPrice(entry.value)}
        </p>
      ))}
    </div>
  )
}

/**
 * Multi-state price chart.
 *
 * Props:
 *   statesData   – { stateAbbr: [{date, avg_price}, ...] }   (one or more states)
 *   stateNames   – { stateAbbr: fullName }   (for legend labels)
 *   nationalData – [{date, avg_price}]        (dashed overlay)
 *   period       – 'weekly' | 'monthly' | 'yearly'
 */
export default function PriceChart({ statesData, stateNames = {}, nationalData, period }) {
  const states = Object.keys(statesData || {})
  const hasData = states.length > 0 && states.some((s) => (statesData[s] || []).length > 0)

  if (!hasData) {
    return (
      <div className="flex items-center justify-center h-80 text-gray-400 text-sm">
        Select a state on the map to view price history
      </div>
    )
  }

  // ── Merge all state data onto a shared date axis ──────────────────────────
  const dateSet = new Set()
  states.forEach((s) => (statesData[s] || []).forEach((d) => dateSet.add(d.date)))

  const byState = {}
  states.forEach((s) => {
    byState[s] = {}
    ;(statesData[s] || []).forEach((d) => { byState[s][d.date] = d.avg_price })
  })

  const nationalByDate = {}
  ;(nationalData || []).forEach((d) => { nationalByDate[d.date] = d.avg_price })

  const sortedDates = [...dateSet].sort()
  const chartData = sortedDates.map((date) => {
    const row = { date }
    states.forEach((s) => { row[s] = byState[s][date] ?? null })
    row.__national = nationalByDate[date] ?? null
    return row
  })

  const tickInterval = Math.max(1, Math.round(sortedDates.length / 12))

  // ── Labels ────────────────────────────────────────────────────────────────
  const labelFor = (key) =>
    key === '__national' ? "Nat'l Avg" : (stateNames[key] || key)

  return (
    <ResponsiveContainer width="100%" height={typeof window !== 'undefined' && window.innerWidth < 640 ? 240 : 340}>
      <LineChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis
          dataKey="date"
          tickFormatter={(v) => formatXAxisTick(v, period)}
          tick={{ fontSize: 11, fill: '#6b7280' }}
          tickLine={false}
          interval={tickInterval}
        />
        <YAxis
          tickFormatter={(v) => `$${Number(v).toFixed(2)}`}
          tick={{ fontSize: 11, fill: '#6b7280' }}
          tickLine={false}
          axisLine={false}
          width={55}
        />
        <Tooltip content={<CustomTooltip period={period} />} />
        <Legend
          wrapperStyle={{ fontSize: '12px', paddingTop: '8px' }}
          formatter={labelFor}
        />

        {/* One colored line per state */}
        {states.map((s, i) => (
          <Line
            key={s}
            type="monotone"
            dataKey={s}
            name={s}
            stroke={STATE_COLORS[i % STATE_COLORS.length]}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
            connectNulls
          />
        ))}

        {/* National average overlay */}
        <Line
          type="monotone"
          dataKey="__national"
          name="__national"
          stroke="#9ca3af"
          strokeWidth={1.5}
          strokeDasharray="5 3"
          dot={false}
          activeDot={{ r: 3 }}
          connectNulls
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
