# Evidence summary

Actual SQLite reservation rows, fictional integer cents.
Six exhaustive order-preserving requested schedules per fixture and mode; not race probabilities.

| Fixture | Mode | Over cap / schedules | Committed totals (cents) |
|---|---|---:|---|
| overlapping_60_60 | separate_check | 4/6 | [6000, 12000] |
| overlapping_60_60 | atomic_reservation | 0/6 | [6000] |
| exact_fill_40_60 | separate_check | 0/6 | [10000] |
| exact_fill_40_60 | atomic_reservation | 0/6 | [10000] |
| small_20_30 | separate_check | 0/6 | [5000] |
| small_20_30 | atomic_reservation | 0/6 | [5000] |
| prior_20_then_50_50 | separate_check | 4/6 | [7000, 12000] |
| prior_20_then_50_50 | atomic_reservation | 0/6 | [7000] |
| one_too_large | separate_check | 0/6 | [2000] |
| one_too_large | atomic_reservation | 0/6 | [2000] |

## Paired trace: separate_check

```json
{
  "fixture": "overlapping_60_60",
  "mode": "separate_check",
  "schedule": [
    "A.check",
    "B.check",
    "A.finish",
    "B.finish"
  ],
  "costs_cents": [
    6000,
    6000
  ],
  "initial_cents": 0,
  "cap_cents": 10000,
  "total_cents": 12000,
  "over_cap": true,
  "rows": [
    {
      "id": "A",
      "cents": 6000
    },
    {
      "id": "B",
      "cents": 6000
    }
  ],
  "outcomes": {
    "A": "reserved",
    "B": "reserved"
  },
  "trace": [
    {
      "request": "A",
      "event": "read_and_check",
      "seen_cents": 0,
      "requested_cents": 6000,
      "permitted": true
    },
    {
      "request": "B",
      "event": "read_and_check",
      "seen_cents": 0,
      "requested_cents": 6000,
      "permitted": true
    },
    {
      "request": "A",
      "event": "reservation_committed",
      "cents": 6000
    },
    {
      "request": "B",
      "event": "reservation_committed",
      "cents": 6000
    }
  ]
}
```

## Paired trace: atomic_reservation

```json
{
  "fixture": "overlapping_60_60",
  "mode": "atomic_reservation",
  "schedule": [
    "A.check",
    "B.check",
    "A.finish",
    "B.finish"
  ],
  "costs_cents": [
    6000,
    6000
  ],
  "initial_cents": 0,
  "cap_cents": 10000,
  "total_cents": 6000,
  "over_cap": false,
  "rows": [
    {
      "id": "A",
      "cents": 6000
    }
  ],
  "outcomes": {
    "A": "reserved",
    "B": "refused"
  },
  "trace": [
    {
      "request": "A",
      "event": "write_transaction_acquired"
    },
    {
      "request": "A",
      "event": "read_and_check",
      "seen_cents": 0,
      "requested_cents": 6000,
      "permitted": true
    },
    {
      "request": "B",
      "event": "busy_no_decision"
    },
    {
      "request": "A",
      "event": "reservation_committed",
      "cents": 6000
    },
    {
      "request": "B",
      "event": "finish_deferred_until_fresh_check"
    },
    {
      "request": "B",
      "event": "fresh_retry"
    },
    {
      "request": "B",
      "event": "write_transaction_acquired"
    },
    {
      "request": "B",
      "event": "read_and_check",
      "seen_cents": 6000,
      "requested_cents": 6000,
      "permitted": false
    },
    {
      "request": "B",
      "event": "rollback_refusal"
    },
    {
      "request": "B",
      "event": "no_reservation"
    }
  ]
}
```

## Limits

The record is a reservation, not money spent. The source bot was not run.
The host must choose the correct shared budget key and trusted price. This tests one SQLite database
and bounded schedules, not distributed checkout, crash recovery, refunds, fairness or live-model behavior.
