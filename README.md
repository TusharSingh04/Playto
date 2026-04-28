# Playto — Production-Grade Merchant Payout Service

A merchant payout system built with Django, Celery, PostgreSQL, and React.

## Free-tier deployment (Render)

Render's free plan does not include Background Workers or Cron Jobs. To
deploy on free tier, the project supports a **cron-pinger mode** instead of
a Celery worker:

- `PAYOUT_USE_CELERY=False` — `POST /payouts` writes the row in `pending`
  and returns. No Celery `.delay()` call.
- A **free external cron service** (e.g. https://cron-job.org) hits
  `POST /api/v1/_internal/cron/sweep/` every 60 seconds with header
  `X-Cron-Secret: <CRON_SECRET>`.
- That endpoint runs the same sweep logic (`apps/payouts/processing.py`)
  with the same DB locking and state-machine guarantees that the Celery
  worker would have applied.

### Steps after Blueprint deploy

1. **Set CRON_SECRET** in `playto-api` → Environment. Generate with:
   ```powershell
   $b = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b)
   ```

2. **Sign up at https://cron-job.org** (free, no card required).

3. **Create a job:**
   - URL: `https://playto-api.onrender.com/api/v1/_internal/cron/sweep/`
   - Schedule: every 1 minute
   - Method: `POST`
   - Header: `X-Cron-Secret: <paste the same value from step 1>`
   - Save & enable.

4. **Verify:** Trigger a payout from the UI. Within ~60 seconds it should
   transition to `completed`/`failed`/`stuck` (and stuck rows clear within
   another minute).

### Trade-offs vs. the Celery setup

| Property | Celery (paid) | Cron-pinger (free) |
|---|---|---|
| Latency to processing | seconds | up to 60s |
| Stuck-detection threshold | 30s, real | 60s minimum |
| External dependency | Redis broker (Render) | cron-job.org liveness |
| State-machine correctness | identical | identical |
| Concurrency safety | identical | identical |
| Spec compliance | full | "async" relaxed to ~60s |

To upgrade to Celery later, set `PAYOUT_USE_CELERY=True`, add a Background
Worker on a paid plan, and disable the cron-job.org job.


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
