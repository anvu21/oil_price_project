import { useState } from 'react'

const PRESETS = [
  { value: '1',   label: '1Y'  },
  { value: '3',   label: '3Y'  },
  { value: '5',   label: '5Y'  },
  { value: '10',  label: '10Y' },
  { value: 'all', label: 'All' },
]

/**
 * Range selector: preset buttons (1Y / 3Y / 5Y / 10Y / All) plus a free
 * number-input for any custom value from 1 to 27 years.
 *
 * Props:
 *   range    – current range value: '1' | '3' | '5' | '10' | 'all' | '<N>'
 *   onChange – called with the new string value
 */
export default function RangeToggle({ range, onChange }) {
  const [customInput, setCustomInput] = useState('')
  const isPreset = PRESETS.some((p) => p.value === range)

  const applyCustom = (raw) => {
    const n = parseInt(raw, 10)
    if (!isNaN(n) && n >= 1 && n <= 27) {
      onChange(String(n))
    }
  }

  const btnBase = 'px-3 py-1.5 text-sm font-medium focus:outline-none transition-colors'
  const btnActive   = `${btnBase} bg-slate-600 text-white`
  const btnInactive = `${btnBase} bg-transparent text-slate-300 border-l border-slate-600 hover:bg-slate-700 hover:text-white`

  return (
    <div className="flex items-center gap-2">
      {/* Preset buttons */}
      <div className="flex rounded-md overflow-hidden border border-slate-600 shadow-sm">
        {PRESETS.map(({ value, label }, i) => (
          <button
            key={value}
            onClick={() => { onChange(value); setCustomInput('') }}
            className={
              range === value
                ? btnActive
                : i === 0 ? `${btnInactive} border-l-0` : btnInactive
            }
          >
            {label}
          </button>
        ))}
      </div>

      {/* Custom year input */}
      <div
        className="flex items-center gap-1"
        title="Type any number of years (1–27) and press Enter"
      >
        <input
          type="number"
          min="1"
          max="27"
          placeholder="?"
          value={!isPreset ? range : customInput}
          onChange={(e) => setCustomInput(e.target.value)}
          onBlur={(e) => applyCustom(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              applyCustom(e.target.value)
              e.target.blur()
            }
          }}
          style={{ MozAppearance: 'textfield' }}
          className={[
            'w-10 rounded border text-center text-sm py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400',
            '[appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none',
            !isPreset
              ? 'bg-slate-600 border-slate-500 text-white'
              : 'bg-transparent border-slate-600 text-slate-300 placeholder-slate-500',
          ].join(' ')}
        />
        <span className="text-slate-400 text-xs font-medium select-none">Y</span>
      </div>
    </div>
  )
}
