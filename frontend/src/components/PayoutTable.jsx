const STATE_STYLES = {
  pending:    "bg-yellow-100 text-yellow-800",
  processing: "bg-blue-100 text-blue-800",
  completed:  "bg-emerald-100 text-emerald-800",
  failed:     "bg-red-100 text-red-800",
};

function fmt(paise) {
  return `₹${(paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
}

function fmtDate(iso) {
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function PayoutTable({ payouts, loading }) {
  if (loading && !payouts.length) {
    return <p className="text-sm text-gray-400 animate-pulse">Loading payouts…</p>;
  }
  if (!payouts.length) {
    return <p className="text-sm text-gray-400">No payouts yet.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-2xl shadow">
      <table className="min-w-full bg-white text-sm">
        <thead>
          <tr className="bg-gray-100 text-left text-xs uppercase tracking-wide text-gray-500">
            <th className="px-4 py-3">ID</th>
            <th className="px-4 py-3">Amount</th>
            <th className="px-4 py-3">Bank (last 4)</th>
            <th className="px-4 py-3">State</th>
            <th className="px-4 py-3">Attempts</th>
            <th className="px-4 py-3">Created</th>
            <th className="px-4 py-3">Reason</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {payouts.map((p) => (
            <tr key={p.id} className="hover:bg-gray-50 transition-colors">
              <td className="px-4 py-3 font-mono text-xs text-gray-400">
                {p.id.slice(0, 8)}…
              </td>
              <td className="px-4 py-3 font-semibold">{fmt(p.amount_paise)}</td>
              <td className="px-4 py-3">****{p.bank_account_last4}</td>
              <td className="px-4 py-3">
                <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATE_STYLES[p.state] ?? "bg-gray-100 text-gray-600"}`}>
                  {p.state}
                </span>
              </td>
              <td className="px-4 py-3 text-center">{p.attempts}</td>
              <td className="px-4 py-3 text-gray-500">{fmtDate(p.created_at)}</td>
              <td className="px-4 py-3 text-gray-400 text-xs">{p.failure_reason || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
