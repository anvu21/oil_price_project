const PERIODS = [
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'yearly', label: 'Yearly' },
]

export default function PeriodToggle({ period, onChange }) {
  return (
    <div className="flex rounded-md overflow-hidden border border-slate-300 shadow-sm">
      {PERIODS.map(({ value, label }) => {
        const isActive = period === value
        return (
          <button
            key={value}
            onClick={() => onChange(value)}
            className={
              isActive
                ? 'px-4 py-2 text-sm font-medium bg-slate-800 text-white focus:outline-none'
                : 'px-4 py-2 text-sm font-medium bg-white text-slate-700 border-l border-slate-300 first:border-l-0 hover:bg-slate-50 focus:outline-none'
            }
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}
