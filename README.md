# Playto — Production-Grade Merchant Payout Service

A merchant payout system built with Django, Celery, PostgreSQL, and React.

## Free-tier deployment (Render)

Render's free plan does not include Background Workers or Cron Jobs. The
project supports two free-tier processing drivers — pick whichever fits.

### Driver A: Dashboard-driven (DEFAULT, zero external setup)

The React dashboard calls `POST /api/v1/payouts/_sweep/` every 10 seconds
while open. The endpoint is authenticated (no shared secret needed) and
rate-limited (10/min/user) so multiple tabs are safe.

**Setup:** none. Deploy the Blueprint, log in, and processing happens
automatically while you have the dashboard open. This is the default
because it works the moment Render finishes deploying.

**Constraint:** when no one is viewing the dashboard, no sweep fires.
Pending payouts sit until someone logs in. On Render free this matches
the platform behavior — the API itself sleeps after 15 min of no traffic.

### Driver B: External cron pinger (more robust, optional)

If you want sweeps to fire even when the dashboard is closed, a free
external cron service can hit `POST /api/v1/_internal/cron/sweep/`
every 60s with an `X-Cron-Secret` header. Two options:

**(B1) cron-job.org** — sign up free, create a job, paste the secret.
Steps in `docs/cron-job-org.md` (or skip — Driver A works without it).

**(B2) GitHub Actions** — `.github/workflows/cron-sweep.yml` runs every
5 min and curls the endpoint. Free for public repos. Reuses your
existing GitHub auth, no new accounts.

Both options require a `CRON_SECRET` env var on the API service plus the
matching value in the cron job's headers. Generate the secret with:

```powershell
$b = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b)
```

### Trade-offs at a glance

| Property | Celery (paid) | Driver A (dashboard) | Driver B (cron pinger) |
|---|---|---|---|
| Latency to processing | seconds | ~10s while dashboard open | up to 60s |
| Fires when no one's looking | yes | no | yes |
| External account | none | none | cron-job.org or GitHub |
| Shared secret | n/a | n/a | required |
| Concurrency / state-machine correctness | identical | identical | identical |

To upgrade to a real worker later, set `PAYOUT_USE_CELERY=True`, add a
Background Worker on a paid Render plan, and disable both drivers.


## Architecture

```
┌─────────────┐     POST /api/v1/payouts      ┌──────────────────┐
│  React UI   │ ────────────────────────────► │  Django API      │
│  (Vite)     │ ◄──────────────────────────── │  (DRF)           │
└─────────────┘     JSON response             └────────┬─────────┘
                                                       │ SELECT FOR UPDATE
                                                       │ INSERT ledger hold
                                                       ▼
                                              ┌──────────────────┐
                                              │   PostgreSQL     │
                                              │   (ledger +      │
                                              │    payouts)      │
                                              └────────▲─────────┘
                                                       │ read/write
                                              ┌────────┴─────────┐
                                              │  Celery Worker   │
                                              │  (Redis broker)  │
                                              └──────────────────┘
                                              ┌──────────────────┐
                                              │  Celery Beat     │
                                              │  poll every 10s  │
                                              └──────────────────┘
```

## Quick Start (Docker)

```bash
git clone <repo>
cd playto
docker compose up --build
```

- API: http://localhost:8000
- Frontend: http://localhost:3000

## Quick Start (Local)

### Prerequisites
- Python 3.12+
- PostgreSQL 16
- Redis 7
- Node 20+

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # edit DB credentials
createdb playto_payouts            # PostgreSQL

python manage.py migrate
python manage.py seed_data         # creates 3 merchants + credit history

# Terminal 1: API
python manage.py runserver

# Terminal 2: Celery worker
celery -A config worker --loglevel=info

# Terminal 3: Celery beat (payout polling every 10s)
celery -A config beat --loglevel=info
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

### Tests

```bash
cd backend
createdb playto_payouts_test
pytest apps/payouts/tests/ apps/ledger/tests/ -v
```

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/merchants/` | List all merchants |
| GET | `/api/v1/merchants/<id>/balance/` | Available + held balance |
| GET | `/api/v1/merchants/<id>/ledger/` | Ledger history (last 50) |
| GET | `/api/v1/merchants/<id>/payouts/` | Payout list |
| POST | `/api/v1/payouts/` | Create payout |
| GET | `/api/v1/payouts/<id>/` | Payout detail |

### Create Payout — Request

```http
POST /api/v1/payouts/
Idempotency-Key: <uuid>
Content-Type: application/json

{
  "merchant_id": "11111111-1111-1111-1111-111111111111",
  "amount_paise": 50000,
  "bank_account_id": "aaaa1111-0000-0000-0000-000000000001"
}
```

### Create Payout — Response (201 Created)

```json
{
  "id": "...",
  "merchant": "...",
  "bank_account": "...",
  "bank_account_last4": "9012",
  "amount_paise": 50000,
  "amount_rupees": "500.00",
  "state": "pending",
  "attempts": 0,
  "failure_reason": "",
  "created_at": "2026-04-28T12:00:00Z",
  "updated_at": "2026-04-28T12:00:00Z"
}
```

Replaying the same `Idempotency-Key` returns **200 OK** with the identical payout.

## Seed Data

| Merchant | Balance | Bank Account |
|----------|---------|--------------|
| Acme Retail Pvt Ltd | ₹50,000 | HDFC — ****9012 |
| Bharat Electronics | ₹20,000 | ICICI — ****1098 |
| Chennai Crafts | ₹5,000 | SBI — ****3222 |

## Payout Lifecycle

```
pending ──► processing ──► completed
                      └──► failed
```

Worker simulation:
- 70% success → ledger: `payout_release` + `payout_debit`, state → completed
- 20% failure → ledger: `payout_release`, state → failed, funds restored
- 10% stuck → re-queued after 30s with exponential backoff; max 3 attempts → failed

## Project Structure

```
playto/
├── backend/
│   ├── apps/
│   │   ├── merchants/          # Merchant, BankAccount models + API
│   │   ├── payouts/            # Payout, IdempotencyKey, service, tasks, tests
│   │   └── ledger/             # LedgerEntry, balance queries, tests
│   ├── config/                 # Django settings, Celery, URLs
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/client.js       # Typed API calls
│   │   ├── hooks/usePolling.js # Live-update polling hook
│   │   ├── components/         # BalanceCard, PayoutForm, PayoutTable, LedgerTable
│   │   └── pages/Dashboard.jsx
│   └── Dockerfile
├── docker-compose.yml
├── README.md
└── EXPLAINER.md
```
