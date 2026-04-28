const TYPE_STYLES = {
  credit:          "text-emerald-600",
  payout_hold:     "text-amber-600",
  payout_debit:    "text-red-600",
  payout_release:  "text-blue-600",
};

function fmtDate(iso) {
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function LedgerTable({ entries }) {
  if (!entries.length) {
    return <p className="text-sm text-gray-400">No ledger entries.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-2xl shadow">
      <table className="min-w-full bg-white text-sm">
        <thead>
          <tr className="bg-gray-100 text-left text-xs uppercase tracking-wide text-gray-500">
            <th className="px-4 py-3">Date</th>
            <th className="px-4 py-3">Type</th>
            <th className="px-4 py-3 text-right">Amount (paise)</th>
            <th className="px-4 py-3 text-right">Amount (₹)</th>
            <th className="px-4 py-3">Reference</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {entries.map((e) => (
            <tr key={e.id} className="hover:bg-gray-50 transition-colors">
              <td className="px-4 py-3 text-gray-500">{fmtDate(e.created_at)}</td>
              <td className={`px-4 py-3 font-mono text-xs font-semibold ${TYPE_STYLES[e.type] ?? ""}`}>
                {e.type}
              </td>
              <td className={`px-4 py-3 text-right font-mono ${e.amount < 0 ? "text-red-600" : "text-emerald-600"}`}>
                {e.amount > 0 ? "+" : ""}{e.amount}
              </td>
              <td className={`px-4 py-3 text-right ${e.amount < 0 ? "text-red-600" : "text-emerald-600"}`}>
                {e.amount > 0 ? "+" : ""}₹{Math.abs(e.amount / 100).toFixed(2)}
              </td>
              <td className="px-4 py-3 font-mono text-xs text-gray-400">
                {e.reference_id.slice(0, 8)}…
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
