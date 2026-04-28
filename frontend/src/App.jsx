import { useEffect, useState } from "react";
import { api, getToken } from "./api/client";
import DemoBanner from "./components/DemoBanner";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";

export default function App() {
  const [merchant, setMerchant] = useState(null);
  const [booting, setBooting] = useState(true);

  // On mount: if we already have a token, validate it via /auth/me/.
  useEffect(() => {
    const token = getToken();
    if (!token) {
      setBooting(false);
      return;
    }
    api
      .whoami()
      .then((data) =>
        setMerchant({
          id: data.merchant_id,
          name: data.name,
          email: data.email,
          bank_accounts: data.bank_accounts,
        })
      )
      .catch(() => api.logout())
      .finally(() => setBooting(false));
  }, []);

  async function handleLoggedIn(_loginData) {
    // Login response is minimal; fetch the full merchant profile (incl. bank
    // accounts) via whoami so the dashboard has everything it needs.
    const data = await api.whoami();
    setMerchant({
      id: data.merchant_id,
      name: data.name,
      email: data.email,
      bank_accounts: data.bank_accounts,
    });
  }

  function handleLogout() {
    api.logout();
    setMerchant(null);
  }

  if (booting) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-gray-400 animate-pulse">Loading…</p>
      </div>
    );
  }

  if (!merchant) {
    return (
      <>
        <DemoBanner />
        <Login onLoggedIn={handleLoggedIn} />
      </>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <DemoBanner />
      <nav className="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="font-bold text-indigo-700 text-lg">Playto Payouts</span>
          <span className="text-sm text-gray-500">— {merchant.name}</span>
        </div>
        <button
          onClick={handleLogout}
          className="text-sm text-gray-500 hover:text-indigo-600 font-medium"
        >
          Sign out
        </button>
      </nav>
      <Dashboard key={merchant.id} merchant={merchant} />
    </div>
  );
}
