const BASE = "/api/v1";

// Token persists across reloads. Cleared on logout / 401.
const TOKEN_KEY = "playto_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request(path, options = {}) {
  const token = getToken();
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Token ${token}` } : {}),
    ...options.headers,
  };
  const res = await fetch(`${BASE}${path}`, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    // Token expired or invalid — surface to UI; App.jsx will route to login.
    setToken(null);
  }
  if (!res.ok) throw { status: res.status, data };
  return data;
}

export const api = {
  // ── Auth ────────────────────────────────────────────────────────────────
  login: async (username, password) => {
    const data = await request("/auth/login/", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setToken(data.token);
    return data; // { token, merchant_id, name }
  },
  logout: () => setToken(null),
  whoami: () => request("/auth/me/"),

  // ── Merchant-scoped reads (merchant_id in URL is checked server-side) ───
  getBalance: (merchantId) => request(`/merchants/${merchantId}/balance/`),
  getLedger: (merchantId) => request(`/merchants/${merchantId}/ledger/`),
  getPayouts: (merchantId) => request(`/merchants/${merchantId}/payouts/`),

  // ── Payout creation ─────────────────────────────────────────────────────
  // No merchant_id in body — server derives it from the auth token.
  createPayout: ({ amountPaise, bankAccountId, idempotencyKey }) =>
    request("/payouts/", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({
        amount_paise: amountPaise,
        bank_account_id: bankAccountId,
      }),
    }),

  // ── Free-tier sweep trigger ─────────────────────────────────────────────
  // On Render free tier there is no Celery worker. The dashboard calls this
  // periodically while open so pending payouts get processed.
  // Server-side rate-limited to 10/min/user, so calling it more often is
  // harmless (excess requests get 429'd).
  triggerSweep: () => request("/payouts/_sweep/", { method: "POST" }),
};
