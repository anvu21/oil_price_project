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

function formatXAxisTick(dateStr, period) {
  if (!dateStr) return ''
  if (period === 'yearly') return dateStr.slice(0, 4)
  if (period === 'monthly') return dateStr.slice(0, 7)
  // weekly — show MM/DD from YYYY-MM-DD
  return dateStr.slice(5)
}

function formatPrice(value) {
  if (value == null) return ''
  return `$${Number(value).toFixed(3)}`
}

function CustomTooltip({ active, payload, label, period }) {
  if (!active || !payload || !payload.length) return null

  let displayDate = label
  if (period === 'yearly') displayDate = label?.slice(0, 4)
  else if (period === 'monthly') displayDate = label?.slice(0, 7)

  return (
    <div className="bg-white border border-gray-200 rounded-md shadow-md px-3 py-2 text-sm">
      <p className="font-medium text-gray-700 mb-1">{displayDate}</p>
      {payload.map((entry) => (
        <p key={entry.name} style={{ color: entry.color }} className="text-xs">
          {entry.name}: {formatPrice(entry.value)}
        </p>
      ))}
    </div>
  )
}

export default function PriceChart({ stateData, nationalData, stateName, period }) {
  const hasData = stateData && stateData.length > 0

  if (!hasData) {
    return (
      <div className="flex items-center justify-center h-80 text-gray-400 text-sm">
        Select a state on the map to view price history
      </div>
    )
  }

  // Merge state and national data by date
  const nationalByDate = {}
  if (nationalData) {
    nationalData.forEach((d) => {
      nationalByDate[d.date] = d.avg_price
    })
  }

  const chartData = stateData.map((d) => ({
    date: d.date,
    statePrice: d.avg_price,
    nationalPrice: nationalByDate[d.date] ?? null,
  }))

  // Choose a tick stride so we get ~12 evenly-spaced labels regardless of
  // how many data points are in the series.  "preserveStartEnd" forces the
  // last tick to always appear, which creates an irregular final gap when the
  // total count isn't a clean multiple of the stride — so we use a fixed
  // integer interval instead and let Recharts trim the last label naturally.
  const tickInterval = Math.max(1, Math.round(chartData.length / 12))

  return (
    <ResponsiveContainer width="100%" height={320}>
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
          formatter={(value) => (value === 'statePrice' ? stateName : 'National Avg')}
        />
        <Line
          type="monotone"
          dataKey="statePrice"
          name="statePrice"
          stroke="#2563eb"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4 }}
        />
        <Line
          type="monotone"
          dataKey="nationalPrice"
          name="nationalPrice"
          stroke="#9ca3af"
          strokeWidth={1.5}
          strokeDasharray="5 3"
          dot={false}
          activeDot={{ r: 3 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
