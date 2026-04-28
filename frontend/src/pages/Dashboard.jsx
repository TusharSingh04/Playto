import { useState, useCallback } from "react";
import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import BalanceCard from "../components/BalanceCard";
import PayoutForm from "../components/PayoutForm";
import PayoutTable from "../components/PayoutTable";
import LedgerTable from "../components/LedgerTable";

export default function Dashboard({ merchant }) {
  const [balance, setBalance] = useState(null);
  const [payouts, setPayouts] = useState([]);
  const [ledger, setLedger] = useState([]);
  const [balanceLoading, setBalanceLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("payouts");
  const [toast, setToast] = useState(null);

  const fetchBalance = useCallback(async () => {
    try {
      const data = await api.getBalance(merchant.id);
      setBalance(data);
    } finally {
      setBalanceLoading(false);
    }
  }, [merchant.id]);

  const fetchPayouts = useCallback(async () => {
    const data = await api.getPayouts(merchant.id);
    setPayouts(data);
  }, [merchant.id]);

  const fetchLedger = useCallback(async () => {
    const data = await api.getLedger(merchant.id);
    setLedger(data);
  }, [merchant.id]);

  // Poll balance + payouts every 3 seconds for live updates
  usePolling(fetchBalance, 3000);
  usePolling(fetchPayouts, 3000);
  usePolling(fetchLedger, 5000);

  function showToast(msg, ok = true) {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 4000);
  }

  function handlePayoutSuccess(payout) {
    showToast(`Payout of ₹${(payout.amount_paise / 100).toFixed(2)} queued (${payout.id.slice(0, 8)}…)`);
    fetchPayouts();
    fetchBalance();
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 rounded-xl shadow-lg px-5 py-3 text-sm font-medium text-white transition-all ${toast.ok ? "bg-emerald-600" : "bg-red-600"}`}>
          {toast.msg}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{merchant.name}</h1>
          <p className="text-sm text-gray-400">{merchant.email}</p>
        </div>
        <span className="text-xs text-gray-300 font-mono">{merchant.id}</span>
      </div>

      {/* Balance */}
      <BalanceCard balance={balance} loading={balanceLoading} />

      {/* Payout form */}
      <PayoutForm merchant={merchant} onSuccess={handlePayoutSuccess} />

      {/* Tabs */}
      <div className="flex gap-2 border-b border-gray-200">
        {["payouts", "ledger"].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium capitalize border-b-2 transition-colors ${
              activeTab === tab
                ? "border-indigo-600 text-indigo-600"
                : "border-transparent text-gray-400 hover:text-gray-600"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "payouts" && (
        <PayoutTable payouts={payouts} loading={balanceLoading} />
      )}
      {activeTab === "ledger" && <LedgerTable entries={ledger} />}
    </div>
  );
}
