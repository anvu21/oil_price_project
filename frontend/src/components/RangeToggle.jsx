const RANGES = [
  { value: '1Y', label: '1Y' },
  { value: '2Y', label: '2Y' },
  { value: '3Y', label: '3Y' },
  { value: 'all', label: 'All' },
]

export default function RangeToggle({ range, onChange }) {
  return (
    <div className="flex rounded-md overflow-hidden border border-slate-600 shadow-sm">
      {RANGES.map(({ value, label }) => {
        const isActive = range === value
        return (
          <button
            key={value}
            onClick={() => onChange(value)}
            className={
              isActive
                ? 'px-3 py-2 text-sm font-medium bg-slate-600 text-white focus:outline-none'
                : 'px-3 py-2 text-sm font-medium bg-transparent text-slate-300 border-l border-slate-600 first:border-l-0 hover:bg-slate-700 hover:text-white focus:outline-none transition-colors'
            }
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}
