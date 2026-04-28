# Playto — Production-Grade Merchant Payout Service

A merchant payout system built with Django, Celery, PostgreSQL, and React.

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
