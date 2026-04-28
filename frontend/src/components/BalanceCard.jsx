export default function BalanceCard({ balance, loading }) {
  const fmt = (paise) =>
    paise == null ? "—" : `₹${(paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;

  return (
    <div className="grid grid-cols-2 gap-4">
      <div className="rounded-2xl bg-white shadow p-6">
        <p className="text-sm text-gray-500 mb-1">Available Balance</p>
        <p className={`text-3xl font-bold ${loading ? "animate-pulse text-gray-300" : "text-emerald-600"}`}>
          {fmt(balance?.available_paise)}
        </p>
      </div>
      <div className="rounded-2xl bg-white shadow p-6">
        <p className="text-sm text-gray-500 mb-1">Held Balance</p>
        <p className={`text-3xl font-bold ${loading ? "animate-pulse text-gray-300" : "text-amber-500"}`}>
          {fmt(balance?.held_paise)}
        </p>
      </div>
    </div>
  );
}
