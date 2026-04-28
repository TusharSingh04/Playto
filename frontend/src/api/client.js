const BASE = "/api/v1";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw { status: res.status, data };
  return data;
}

export const api = {
  getMerchants: () => request("/merchants/"),

  getBalance: (merchantId) => request(`/merchants/${merchantId}/balance/`),

  getLedger: (merchantId) => request(`/merchants/${merchantId}/ledger/`),

  getPayouts: (merchantId) => request(`/merchants/${merchantId}/payouts/`),

  createPayout: ({ merchantId, amountPaise, bankAccountId, idempotencyKey }) =>
    request("/payouts/", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({
        merchant_id: merchantId,
        amount_paise: amountPaise,
        bank_account_id: bankAccountId,
      }),
    }),
};
