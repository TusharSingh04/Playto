import { useState } from "react";
import { api } from "../api/client";

function generateUUID() {
  return crypto.randomUUID();
}

export default function PayoutForm({ merchant, onSuccess }) {
  const [amountRupees, setAmountRupees] = useState("");
  const [bankAccountId, setBankAccountId] = useState(
    merchant?.bank_accounts?.[0]?.id ?? ""
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const bankAccounts = merchant?.bank_accounts ?? [];

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);

    const rupees = parseFloat(amountRupees);
    if (isNaN(rupees) || rupees < 1) {
      setError("Minimum payout amount is ₹1.");
      return;
    }

    const amountPaise = Math.round(rupees * 100);

    setLoading(true);
    try {
      // merchant_id is no longer sent — the server derives it from the
      // auth token. Sending it from here would just be ignored.
      const payout = await api.createPayout({
        amountPaise,
        bankAccountId,
        idempotencyKey: generateUUID(),
      });
      setAmountRupees("");
      onSuccess(payout);
    } catch (err) {
      const detail =
        err?.data?.detail ?? err?.data?.error ?? "Something went wrong.";
      setError(typeof detail === "string" ? detail : JSON.stringify(detail));
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-2xl bg-white shadow p-6 space-y-4">
      <h2 className="text-lg font-semibold text-gray-800">Request Payout</h2>

      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div>
        <label className="block text-sm font-medium text-gray-600 mb-1">
          Amount (₹)
        </label>
        <input
          type="number"
          min="1"
          step="0.01"
          value={amountRupees}
          onChange={(e) => setAmountRupees(e.target.value)}
          placeholder="e.g. 500"
          required
          className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-600 mb-1">
          Bank Account
        </label>
        <select
          value={bankAccountId}
          onChange={(e) => setBankAccountId(e.target.value)}
          required
          className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        >
          {bankAccounts.map((ba) => (
            <option key={ba.id} value={ba.id}>
              {ba.account_holder_name} — ****{ba.account_number.slice(-4)} ({ba.ifsc_code})
            </option>
          ))}
        </select>
      </div>

      <button
        type="submit"
        disabled={loading}
        className="w-full rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 text-white font-semibold py-2 text-sm transition-colors"
      >
        {loading ? "Processing…" : "Submit Payout"}
      </button>
    </form>
  );
}
