export default function KPICard({ label, value, hint, accent = "blue", testId }) {
  const accents = {
    blue: "text-blue-600",
    yellow: "text-yellow-700",
    emerald: "text-emerald-600",
    red: "text-red-600",
    slate: "text-slate-900",
  };
  return (
    <div
      data-testid={testId}
      className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm hover:-translate-y-[2px] hover:shadow-md transition-all duration-200"
    >
      <div className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className={`mt-3 text-3xl md:text-4xl font-display font-bold tracking-tighter ${accents[accent] || accents.blue}`}>
        {value}
      </div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}
