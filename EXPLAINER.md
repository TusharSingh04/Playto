# EXPLAINER — Design Decisions & Deep Dives

## 1. Ledger System

### Exact SQL for Balance

Django ORM generates the following SQL for `get_merchant_balance(merchant_id)`:

```sql
SELECT
  COALESCE(SUM("ledger_entries"."amount"), 0) AS "available_paise",
  COALESCE(
    -(SUM("ledger_entries"."amount")
      FILTER (WHERE "ledger_entries"."type" IN ('payout_hold', 'payout_release'))
    ),
    0
  ) AS "held_paise"
FROM "ledger_entries"
WHERE "ledger_entries"."merchant_id" = '<uuid>';
```

**Available balance** = `SUM(amount)` over all entries.

Because amounts are signed:

| Entry type       | Amount | Effect on available |
|------------------|--------|---------------------|
| `credit`         | +X     | +X                  |
| `payout_hold`    | -X     | -X (reserved)       |
| `payout_release` | +X     | +X (returned)       |
| `payout_debit`   | -X     | -X (permanent)      |

**Held balance** = `-SUM(amount WHERE type IN ('payout_hold', 'payout_release'))`

For a pending payout: hold=-X, no release yet → held = -(-X) = X ✓  
For a completed payout: hold=-X, release=+X → held = -(−X+X) = 0 ✓  
For a failed payout: hold=-X, release=+X → held = 0 ✓ (funds restored)

### Why This Model Prevents Drift

1. **Append-only.** `LedgerEntry` rows are never updated or deleted. Balance is always derived fresh from the ledger. There is no cached `balance` column to get out of sync.

2. **Single source of truth.** The balance is not stored anywhere else. The API, the worker, and the tests all call the same `get_merchant_balance()` function which always hits the DB.

3. **Invariant:** `SUM(all ledger amounts) >= 0` at all times, enforced by the locking strategy (see §2) which prevents over-spending.

4. **No floats.** All amounts are `BigIntegerField` in paise. No rounding errors, no `Decimal` gotchas, no `0.1 + 0.2 ≠ 0.3`.

---

## 2. Concurrency

### The Failure Scenario

Merchant has ₹100. Two parallel requests each want ₹60.

Without locking:

```
Thread A: reads balance = 10,000 paise ✓
Thread B: reads balance = 10,000 paise ✓  ← sees stale state
Thread A: inserts hold -6,000
Thread B: inserts hold -6,000             ← double-spend!
Net balance: -2,000 paise                 ← CATASTROPHIC
```

### The Locking Code

```python
# apps/payouts/service.py — create_payout()

with transaction.atomic():
    # 1. Lock the merchant row — all concurrent payout creators for this merchant
    #    will block here until we COMMIT or ROLLBACK.
    merchant = Merchant.objects.select_for_update().get(pk=merchant_id)

    # 2. Aggregate balance AFTER acquiring the lock.
    #    No other transaction can insert ledger entries for this merchant
    #    until our transaction ends, so this aggregate is stable.
    balance = get_merchant_balance(merchant_id)

    if balance["available_paise"] < amount_paise:
        raise InsufficientFundsError(...)

    # 3. Insert payout + hold atomically inside the same transaction.
    payout = Payout.objects.create(...)
    LedgerEntry.objects.create(amount=-amount_paise, type='payout_hold', ...)
```

PostgreSQL translates `select_for_update()` to:

```sql
SELECT * FROM merchants WHERE id = '<uuid>' FOR UPDATE;
```

### Why It Is Safe

- `FOR UPDATE` places an **exclusive row lock** on the merchant row for the duration of the transaction.
- Any concurrent transaction that hits `SELECT ... FOR UPDATE` on the same row **blocks** until the first transaction commits or rolls back.
- After the first transaction commits, the second transaction acquires the lock, re-runs the aggregate (now including the first hold), and correctly sees insufficient funds.
- Lock scope is minimal: one merchant row, not the entire table.
- No application-level locks (mutexes, Redis locks) are used. The database is the arbiter.

---

## 3. Idempotency

### Storage

`IdempotencyKey` table:

```
(merchant_id, key)  ← unique constraint
status              ← in_progress | complete
response_snapshot   ← full JSON of the payout response
expires_at          ← NOW() + 24h
```

### Enforcement Flow

```
Incoming request with Idempotency-Key: K
│
├─ SELECT ... FOR UPDATE WHERE merchant=M AND key=K AND expires_at > NOW()
│
├─ Found, status=complete  → return stored response_snapshot  (200 OK)
│
├─ Found, status=in_progress → raise IdempotencyConflictError  (409)
│
└─ Not found:
      INSERT idempotency_key (status=in_progress)
      → check balance
      → create payout + hold
      → UPDATE idempotency_key SET status=complete, payout=<id>
      → return payout  (201 Created)
```

### Race Condition Handling

Two parallel requests with the same key arrive simultaneously:

1. Both enter `transaction.atomic()`.
2. Both hit `SELECT FOR UPDATE` on the idempotency key row.
3. One acquires the lock; the other **blocks**.
4. Winner proceeds: creates the `in_progress` record, processes the payout, marks `complete`.
5. Loser unblocks, re-reads the row, sees `status=complete`, returns the stored snapshot.

If the winner crashes mid-flight, the loser sees `status=in_progress` and returns 409, telling the caller to retry. The `in_progress` record acts as a mutex.

### Why Not Just Cache It

A cache (Redis, memcached) is not durable. If the cache evicts the key or the cache node restarts, a duplicate payout can slip through. The DB record is atomic with the payout creation itself — they live and die in the same transaction.

### Insufficient Funds Edge Case

If the balance check fails, the `in_progress` idempotency key is **deleted** before the exception propagates. This lets the merchant retry with the same key after topping up. We do not store a "failed" idempotency record for business-rule rejections.

---

## 4. State Machine

### Legal Transitions

```python
VALID_TRANSITIONS = {
    "pending":    ["processing"],
    "processing": ["completed", "failed"],
    "completed":  [],
    "failed":     [],
}
```

### Where Illegal Transitions Are Blocked

**`Payout.transition_to(new_state)`** in `apps/payouts/models.py`:

```python
def transition_to(self, new_state: str) -> "Payout":
    allowed = VALID_TRANSITIONS.get(self.state, [])
    if new_state not in allowed:
        raise PayoutTransitionError(...)     # ← software guard

    updated = Payout.objects.filter(
        pk=self.pk,
        state=self.state          # ← database guard (optimistic lock)
    ).update(state=new_state, ...)

    if updated == 0:
        raise PayoutTransitionError(
            "Concurrent modification: state was already changed."
        )
```

Two guards operate independently:

1. **Software guard** — checks `VALID_TRANSITIONS` before touching the DB.  
   Catches all logically invalid transitions (e.g. `completed → failed`).

2. **Database guard (optimistic lock)** — `filter(state=self.state)` means the `UPDATE` only touches rows where the state is *still* what we expect.  
   If a concurrent worker already advanced the state, `updated == 0` and we raise instead of silently overwriting.

This means even if two workers both call `transition_to(PROCESSING)` on the same payout simultaneously, exactly one succeeds and the other raises `PayoutTransitionError` and exits cleanly.

---

## 5. AI Audit — Incorrect Snippet & Correction

### The Incorrect Snippet

This is the kind of code an AI (or a junior engineer) commonly generates for payout creation:

```python
# ❌ WRONG — race condition and float danger

def create_payout(merchant_id, amount_rupees, bank_account_id):
    merchant = Merchant.objects.get(pk=merchant_id)
    
    # Compute balance in Python from fetched rows
    entries = LedgerEntry.objects.filter(merchant=merchant)
    balance_rupees = sum(
        float(e.amount_rupees) for e in entries   # ← float conversion
    )
    
    # Check-then-act gap — another thread can insert a hold here
    if balance_rupees < amount_rupees:
        raise InsufficientFundsError("Not enough balance")
    
    payout = Payout.objects.create(
        merchant=merchant,
        amount_paise=int(amount_rupees * 100),    # ← float multiply
        state="pending",
    )
    LedgerEntry.objects.create(
        merchant=merchant,
        amount=-int(amount_rupees * 100),         # ← float multiply again
        type="payout_hold",
    )
    return payout
```

### Why It Is Wrong

| Problem | Consequence |
|---------|-------------|
| `float(e.amount_rupees)` | Floating-point rounding. ₹0.1 + ₹0.2 ≠ ₹0.3 in IEEE 754. |
| `amount_rupees * 100` as float | `50.10 * 100 = 5009.999...` → `int(...)` = 5009 paise, not 5010. |
| `sum(...)` in Python | Fetches all rows to application memory. Slow, O(n), wrong. |
| No `transaction.atomic()` | Payout created, then crash before ledger insert → inconsistent state. |
| No `SELECT FOR UPDATE` | Classic TOCTOU race: two threads both read "sufficient balance", both create holds, double-spend. |
| No idempotency | Retry after network timeout creates a second payout. |

### The Corrected Version

```python
# ✅ CORRECT — see apps/payouts/service.py for full implementation

def create_payout(*, merchant_id, bank_account_id, amount_paise, idempotency_key_str):
    if amount_paise <= 0:
        raise ValueError("amount_paise must be positive")

    with transaction.atomic():
        # Exclusive lock prevents concurrent payout creation for this merchant
        merchant = Merchant.objects.select_for_update().get(pk=merchant_id)

        # DB aggregate — no Python arithmetic, no float
        balance = LedgerEntry.objects.filter(
            merchant_id=merchant_id
        ).aggregate(
            available_paise=Coalesce(Sum("amount"), Value(0))
        )

        if balance["available_paise"] < amount_paise:
            raise InsufficientFundsError(...)

        payout = Payout.objects.create(
            merchant=merchant,
            bank_account_id=bank_account_id,
            amount_paise=amount_paise,       # integer, already in paise
            state=PayoutState.PENDING,
        )
        LedgerEntry.objects.create(
            merchant=merchant,
            amount=-amount_paise,            # integer, signed
            type=LedgerEntryType.PAYOUT_HOLD,
            reference_id=payout.id,
        )
    return payout
```

Key corrections:
- `amount_paise` accepted as integer — caller converts, no float inside the service.
- `SELECT FOR UPDATE` serialises concurrent requests.
- `SUM()` runs in the database, after the lock is held.
- Everything inside `transaction.atomic()`.

---

## Bonus: What Wasn't Built

The following are excluded because the spec asked for clean implementation over checkbox coverage:

- **Webhooks** — would require a `WebhookEndpoint` model, outbox pattern, and a separate delivery worker. Not a small addition.
- **Full audit log** — ledger entries serve as an implicit audit trail. A separate audit model would duplicate them.
- **Event sourcing** — the append-only ledger *is* event sourcing for the financial domain. A full ES framework would add complexity without correctness benefit here.
