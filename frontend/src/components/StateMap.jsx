import { useState, useMemo } from 'react'
import { ComposableMap, Geographies, Geography } from 'react-simple-maps'
import { scaleLinear } from 'd3-scale'

const GEO_URL = 'https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json'

// FIPS numeric code -> state abbreviation
const FIPS_TO_ABBR = {
  '01': 'AL', '02': 'AK', '04': 'AZ', '05': 'AR', '06': 'CA',
  '08': 'CO', '09': 'CT', '10': 'DE', '11': 'DC', '12': 'FL',
  '13': 'GA', '15': 'HI', '16': 'ID', '17': 'IL', '18': 'IN',
  '19': 'IA', '20': 'KS', '21': 'KY', '22': 'LA', '23': 'ME',
  '24': 'MD', '25': 'MA', '26': 'MI', '27': 'MN', '28': 'MS',
  '29': 'MO', '30': 'MT', '31': 'NE', '32': 'NV', '33': 'NH',
  '34': 'NJ', '35': 'NM', '36': 'NY', '37': 'NC', '38': 'ND',
  '39': 'OH', '40': 'OK', '41': 'OR', '42': 'PA', '44': 'RI',
  '45': 'SC', '46': 'SD', '47': 'TN', '48': 'TX', '49': 'UT',
  '50': 'VT', '51': 'VA', '53': 'WA', '54': 'WV', '55': 'WI',
  '56': 'WY',
}

// State abbreviation -> full name
const ABBR_TO_NAME = {
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

// Diverging scale: blue (cheap) → light gray (median) → red (expensive)
// Midpoint ~$4.25 matches rough national average
const colorScale = scaleLinear()
  .domain([2.5, 4.25, 6.5])
  .range(['#1e40af', '#e5e7eb', '#b91c1c'])
  .clamp(true)

const PADD_NAMES = {
  R1X: 'New England (PADD 1A)',
  R1Y: 'Central Atlantic (PADD 1B)',
  R1Z: 'Lower Atlantic (PADD 1C)',
  R20: 'Midwest (PADD 2)',
  R30: 'Gulf Coast (PADD 3)',
  R40: 'Rocky Mountain (PADD 4)',
  R50: 'West Coast (PADD 5)',
}

const STATE_TO_PADD = {
  CT:'R1X', ME:'R1X', NH:'R1X', RI:'R1X', VT:'R1X',
  DC:'R1Y', DE:'R1Y', MD:'R1Y', NJ:'R1Y', PA:'R1Y',
  GA:'R1Z', NC:'R1Z', SC:'R1Z', VA:'R1Z', WV:'R1Z',
  IL:'R20', IN:'R20', IA:'R20', KS:'R20', KY:'R20',
  MI:'R20', MO:'R20', NE:'R20', ND:'R20', OK:'R20',
  SD:'R20', TN:'R20', WI:'R20',
  AL:'R30', AR:'R30', LA:'R30', MS:'R30', NM:'R30',
  ID:'R40', MT:'R40', UT:'R40', WY:'R40',
  AK:'R50', AZ:'R50', HI:'R50', NV:'R50', OR:'R50',
}

/**
 * Props:
 *   prices          – latest price array from the API
 *   selectedStates  – array of state abbreviations to highlight (amber outline)
 *   onStateSelect   – called with abbr when user clicks a state
 *   compareMode     – when true, tooltip hints "click to add/remove" instead of "click for history"
 */
export default function StateMap({ prices, selectedStates = [], onStateSelect, compareMode = false }) {
  const [tooltip, setTooltip] = useState(null)
  const selectedSet = useMemo(() => new Set(selectedStates), [selectedStates])

  const priceByState = useMemo(() => {
    if (!prices) return {}
    return Object.fromEntries(prices.map((d) => [d.state, d.avg_price]))
  }, [prices])

  const sourceByState = useMemo(() => {
    if (!prices) return {}
    return Object.fromEntries(prices.map((d) => [d.state, d.source || 'state']))
  }, [prices])

  // null  → still fetching (show skeleton)
  // []    → fetched but DB is empty (render map in gray + banner)
  if (prices === null) {
    return <div className="w-full h-64 bg-gray-200 animate-pulse rounded-md" />
  }

  return (
    <div className="relative w-full">
      <ComposableMap
        projection="geoAlbersUsa"
        style={{ width: '100%', height: 'auto' }}
      >
        <Geographies geography={GEO_URL}>
          {({ geographies }) =>
            geographies.map((geo) => {
              const fips = geo.id?.toString().padStart(2, '0')
              const abbr = FIPS_TO_ABBR[fips]
              const price = abbr ? priceByState[abbr] : undefined
              const isSelected = abbr ? selectedSet.has(abbr) : false

              const choroplethFill = price != null ? colorScale(price) : '#d1d5db'
              const fill    = isSelected ? '#f59e0b' : choroplethFill   // amber when selected
              const source  = abbr ? sourceByState[abbr] : undefined
              const hasData = price != null

              const actionHint = compareMode
                ? (isSelected ? 'click to remove' : 'click to add')
                : 'click for history'

              return (
                <Geography
                  key={geo.rsmKey}
                  geography={geo}
                  onClick={() => { if (abbr && hasData) onStateSelect(abbr) }}
                  onMouseEnter={(evt) => {
                    if (abbr) {
                      const padd = STATE_TO_PADD[abbr]
                      setTooltip({
                        x:          evt.clientX,
                        y:          evt.clientY,
                        name:       ABBR_TO_NAME[abbr] || abbr,
                        price,
                        isRegional: source === 'region',
                        regionName: padd ? PADD_NAMES[padd] : null,
                        actionHint,
                      })
                    }
                  }}
                  onMouseMove={(evt) => {
                    setTooltip((prev) =>
                      prev ? { ...prev, x: evt.clientX, y: evt.clientY } : null
                    )
                  }}
                  onMouseLeave={() => setTooltip(null)}
                  style={{
                    default: {
                      fill,
                      stroke: isSelected ? '#b45309' : '#ffffff',
                      strokeWidth: isSelected ? 2 : 0.6,
                      outline: 'none',
                      cursor: hasData ? 'pointer' : 'default',
                    },
                    hover: {
                      fill: hasData ? (isSelected ? '#fbbf24' : choroplethFill) : '#d1d5db',
                      stroke: hasData ? (isSelected ? '#92400e' : '#1e293b') : '#9ca3af',
                      strokeWidth: hasData ? (isSelected ? 2.5 : 1.5) : 0.6,
                      outline: 'none',
                      cursor: hasData ? 'pointer' : 'not-allowed',
                      opacity: hasData ? 0.85 : 1,
                    },
                    pressed: {
                      fill,
                      stroke: '#1e293b',
                      strokeWidth: 2,
                      outline: 'none',
                    },
                  }}
                />
              )
            })
          }
        </Geographies>
      </ComposableMap>

      {/* Legend */}
      <div className="mt-1 px-2">
        <p className="text-xs font-medium text-gray-500 mb-1">National Retail Prices ($/gal)</p>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span className="text-blue-700 font-medium">Lowest</span>
          <div
            className="h-3 flex-1 rounded"
            style={{
              background: 'linear-gradient(to right, #1e40af, #e5e7eb, #b91c1c)',
            }}
          />
          <span className="text-red-700 font-medium">Highest</span>
        </div>
        <div className="flex justify-between text-xs text-gray-400 mt-0.5">
          <span>$2.50</span>
          <span>$4.25 avg</span>
          <span>$6.50+</span>
        </div>
      </div>

      {/* Hover tooltip */}
      {tooltip && (
        <div
          className="fixed z-50 pointer-events-none bg-slate-900 text-white rounded-lg shadow-xl px-3 py-2 text-sm"
          style={{ left: tooltip.x + 14, top: tooltip.y - 42 }}
        >
          <p className="font-semibold">{tooltip.name}</p>
          {tooltip.price != null ? (
            <>
              <p className="text-slate-300 text-xs mt-0.5">
                ${Number(tooltip.price).toFixed(3)}/gal · {tooltip.actionHint}
              </p>
              {tooltip.isRegional && tooltip.regionName && (
                <p className="text-amber-400 text-xs mt-0.5">
                  Regional avg — {tooltip.regionName}
                </p>
              )}
            </>
          ) : (
            <p className="text-slate-400 text-xs mt-0.5">No data available</p>
          )}
        </div>
      )}
    </div>
  )
}
