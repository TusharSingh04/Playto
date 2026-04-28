import { useState, useEffect } from "react";
import { api } from "./api/client";
import Dashboard from "./pages/Dashboard";

export default function App() {
  const [merchants, setMerchants] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getMerchants()
      .then((data) => {
        setMerchants(data);
        if (data.length > 0) setSelected(data[0]);
      })
      .catch(() => setError("Could not reach the API. Is the backend running?"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-gray-400 animate-pulse">Loading merchants…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="rounded-xl bg-red-50 border border-red-200 px-8 py-6 text-center">
          <p className="text-red-600 font-semibold">{error}</p>
          <p className="text-sm text-gray-500 mt-2">Start the Django server and refresh.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top nav / merchant switcher */}
      <nav className="bg-white border-b border-gray-200 px-4 py-3 flex items-center gap-4">
        <span className="font-bold text-indigo-700 text-lg">Playto Payouts</span>
        <div className="flex gap-2 ml-4">
          {merchants.map((m) => (
            <button
              key={m.id}
              onClick={() => setSelected(m)}
              className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${
                selected?.id === m.id
                  ? "bg-indigo-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {m.name}
            </button>
          ))}
        </div>
      </nav>

      {selected ? (
        <Dashboard key={selected.id} merchant={selected} />
      ) : (
        <p className="text-center mt-20 text-gray-400">No merchants found. Run seed_data.</p>
      )}
    </div>
  );
}
