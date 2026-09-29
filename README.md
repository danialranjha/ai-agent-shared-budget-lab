# Shared-budget reservations for AI-agent actions

An offline, synthetic SQLite experiment: two individually affordable requests can overbook a shared budget when their checks finish before either reservation is recorded.

This is an independent design experiment, **not** source code from a shopping bot or a reproduction of a vendor vulnerability. No model, network, shell command, credential, checkout or payment is used by the experiment. Only disposable local reservation records change.

## Hypothesis

For a 100-unit owner/day budget and two 60-unit requests, separate reads followed by later writes can record 120. Acquiring a SQLite write transaction before reading, then checking and recording before committing, keeps the tested aggregate at or below 100. A contender must retry the entire check after a busy result; it must not reuse an old approval.

## Motivation and sources

A [personal-bots issue](https://github.com/jigar-dhulla/personal-bots/issues/34) proposes trusted daily spend caps. It does not report this race or prescribe this implementation. We derive the concurrency question independently from that requirement. The experiment does not test its per-line limits, confirmation flow, product code or prompt-injection resistance.

SQLite documents [one simultaneous write transaction and BEGIN IMMEDIATE](https://sqlite.org/lang_transaction.html), and [isolation between separate connections](https://sqlite.org/isolation.html). This lab uses those documented semantics, without claiming a new database finding.

## Threat model and containment

- An agent or other caller can submit two requests against the same shared budget. Overlap can be accidental; no successful model manipulation is assumed or measured.
- The host, prices, cap, owner/day assignment, database and reservation implementation are trusted. The caller cannot edit the ledger or use another recording path.
- All amounts are positive integer cents. The fixed budget is 10,000 cents. The strings owner-demo/day-demo are fictional scope labels, not real identities or dates.
- Two connections open one SQLite file inside a freshly created temporary directory. An explicit scheduler overlaps their transaction lifetimes; no timing-sensitive threads, subprocesses, real shopping API or external effect are required.
- The sink is **committed reservation rows**, not actual spending. An approved check alone does not count as a reserved amount.

## Setup and exact commands

Python 3.11+ with its standard-library SQLite support; no third-party packages.

```sh
python3 experiment.py
python3 -m unittest discover -s tests -v
python3 run_checks.py
```

The first command writes [artifacts/run.json](artifacts/run.json) and [evidence.md](evidence.md). The last records [tests.json](artifacts/tests.json) and [mutations.json](artifacts/mutations.json). All result JSON is deterministic and excludes temporary paths, timestamps and host information. Development validation used Python 3.11.6. Test your deployment's database behavior separately.

## Results

Five fixtures × six requested schedules × two methods = 60 cases (30 paired schedules). There are no sampled attacks or race-probability estimates.

| Fixture | Separate check: over cap / schedules | Atomic reservation: over cap / schedules | Atomic final total |
|---|---:|---:|---:|
|60+60, initially 0 |4/6 |0/6 |60 |
|40+60 exact fill |0/6 |0/6 |100 |
|20+30 small orders |0/6 |0/6 |50 |
|50+50, already 20 reserved |4/6 |0/6 |70 |
|110+20 |0/6 |0/6 |20 |

These are fictional currency units; JSON stores cents. The two requests in a schedule have fixed IDs A/B. Either can be the first writer. Both methods preserve the exact-fill twin in all six schedules. Both refuse the single 110-unit request. The atomic method has no over-cap record in these 30 cases; this is a bounded result, not proof of all production behavior.

Twelve focused tests pass. Removing the transaction scope produces four invariant failures in the six 60+60 schedules. Changing <= to < refuses the legitimate exact fill in all six schedules. [Mutation details](artifacts/mutations.json).

## Technical walkthrough

For requested order A.check, B.check, A.finish, B.finish:

| Step | Separate check | Atomic reservation |
|---|---|---|
| A begins | Reads 0, approves 60; no transaction retained | Acquires writer, reads 0, approves 60; transaction retained |
| B begins before A records | Reads 0, also approves 60 | BEGIN IMMEDIATE returns SQLITE_BUSY; no read, decision or record |
| A finishes | Inserts 60 in its own autocommit transaction | Inserts 60 and commits its existing transaction |
| B finishes / retries | Inserts another 60 using the earlier decision | Retries whole check, reads 60, refuses another 60, rolls back |
| Committed rows | A 60 + B 60 = 120 | A 60 only; total 60 |

The intervention does **not** approve B while making it wait for a later insert. B gets no budget decision until it has acquired the transaction and read the updated ledger. It also does not reduce B to 40 or charge a payment.

The six schedules enumerate all permutations of A.check/A.finish/B.check/B.finish that preserve each request's check-before-finish order. For the atomic method, an attempted check may be busy and its finish is deferred. After the first writer finishes, the blocked request retries the full operation. Therefore the requested interleavings are paired, while actual execution order differs as the intervention intends. Exact traces expose this distinction.

`Attempt.check` and `Attempt.finish` deliberately separate the scheduling points. Production code should own their transaction lifecycle in one trusted reservation operation. The control also uses valid SQLite autocommit statements: the weakness is application-level separation of the read from the later write, not a broken database transaction. SQL statements are parameterized.

## Limitations

- No source-bot code, current deployment, AI model or prompt-injection attack was tested. The issue motivates the experiment; it does not establish that this race exists in that project.
- One trusted owner/day key and price are prerequisites. Different keys split the budget; a unit test makes this visible. Timezone rollover, wrong owner assignment and price changes are not fixed by locking.
- Reservation is not payment. Distributed services, external checkout, failed payments, cancellation, refunds, durable outboxes, idempotent external retries and crash recovery require separate design and tests.
- SQLite contention is exercised deterministically with two real connections, not sampled under concurrent workload. No latency, fairness, availability or real-world frequency claim is made. One database serializes writers broadly; throughput was not measured.
- Invalid/nonpositive/noninteger costs are refused, but the fixture harness is not a general untrusted-request parser or deployable service. The schema has no universal budget constraint; callers bypassing this code can violate the cap.
- A budget limits the amount reserved, not whether an order is appropriate, who may order, its delivery address, or whether a model's reasoning was safe.

## Engineering check supported by this result

In this single-database design, acquire the write transaction before reading the shared budget, check the new total, record the reservation and commit before allowing downstream work. Add an overlapping-request test and an exact-fill twin; after contention, retry with a fresh read rather than a cached approval. Validate external checkout and failure handling separately.
