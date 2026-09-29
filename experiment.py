"""Contained shared-budget reservation experiment. No checkout or network."""
import itertools
import json
import sqlite3
import tempfile
from pathlib import Path

CAP = 10000  # integer cents, fictional currency
BUCKET = ("owner-demo", "day-demo")
MODES = ("separate_check", "atomic_reservation")
FIXTURES = (
    {"id": "overlapping_60_60", "costs": (6000, 6000), "initial": 0},
    {"id": "exact_fill_40_60", "costs": (4000, 6000), "initial": 0},
    {"id": "small_20_30", "costs": (2000, 3000), "initial": 0},
    {"id": "prior_20_then_50_50", "costs": (5000, 5000), "initial": 2000},
    {"id": "one_too_large", "costs": (11000, 2000), "initial": 0},
)


def valid_cost(value):
    return type(value) is int and 0 < value <= 10**9


def schedules():
    return [p for p in itertools.permutations(("A.check", "A.finish", "B.check", "B.finish"))
            if p.index("A.check") < p.index("A.finish")
            and p.index("B.check") < p.index("B.finish")]


def connect(path):
    return sqlite3.connect(path, isolation_level=None, timeout=0)


def total(conn, bucket=BUCKET):
    return conn.execute(
        "SELECT COALESCE(SUM(cents),0) FROM reservations WHERE owner=? AND day=?", bucket
    ).fetchone()[0]


def initialize(conn, initial=0):
    conn.execute("CREATE TABLE reservations (id TEXT PRIMARY KEY, owner TEXT NOT NULL, "
                 "day TEXT NOT NULL, cents INTEGER NOT NULL CHECK(cents>0))")
    if initial:
        conn.execute("INSERT INTO reservations VALUES (?,?,?,?)", ("prior", *BUCKET, initial))


class Attempt:
    def __init__(self, conn, name, cents, mode, trace, *, strict=False):
        self.conn, self.name, self.cents, self.mode, self.trace = conn, name, cents, mode, trace
        self.strict = strict
        self.state = "new"

    def emit(self, event, **fields):
        self.trace.append({"request": self.name, "event": event, **fields})

    def check(self):
        if self.state not in ("new", "busy"):
            raise ValueError("check must be new or fresh retry")
        if not valid_cost(self.cents):
            self.state = "invalid"
            self.emit("invalid_cost")
            return
        if self.mode == "atomic_reservation":
            try:
                self.conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                if exc.sqlite_errorcode != sqlite3.SQLITE_BUSY:
                    raise
                self.state = "busy"
                self.emit("busy_no_decision")
                return
            self.emit("write_transaction_acquired")
        seen = total(self.conn)
        permitted = seen + self.cents < CAP if self.strict else seen + self.cents <= CAP
        self.state = "approved" if permitted else "refused"
        self.emit("read_and_check", seen_cents=seen, requested_cents=self.cents, permitted=permitted)
        if not permitted and self.mode == "atomic_reservation":
            self.conn.execute("ROLLBACK")
            self.emit("rollback_refusal")

    def finish(self):
        if self.state == "busy":
            self.emit("finish_deferred_until_fresh_check")
            return
        if self.state in ("refused", "invalid"):
            self.emit("no_reservation")
            return
        if self.state != "approved":
            raise ValueError("finish requires an approved check")
        try:
            self.conn.execute("INSERT INTO reservations VALUES (?,?,?,?)",
                              (self.name, *BUCKET, self.cents))
            if self.mode == "atomic_reservation":
                self.conn.execute("COMMIT")
        except Exception:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise
        self.state = "reserved"
        self.emit("reservation_committed", cents=self.cents)


def run_case(costs, mode, schedule, initial=0, *, strict=False):
    if mode not in MODES or tuple(schedule) not in schedules():
        raise ValueError("unknown mode or schedule")
    if len(costs) != 2 or type(initial) is not int or not 0 <= initial <= CAP:
        raise ValueError("invalid fixture")
    trace = []
    with tempfile.TemporaryDirectory(prefix="budget-lab-") as directory:
        path = Path(directory) / "reservations.sqlite"
        conns = [connect(path), connect(path)]
        try:
            initialize(conns[0], initial)
            attempts = {name: Attempt(conn, name, cents, mode, trace, strict=strict)
                        for name, conn, cents in zip(("A", "B"), conns, costs)}
            for token in schedule:
                name, operation = token.split(".")
                getattr(attempts[name], operation)()
            # A blocked BEGIN made no decision. Retry the ENTIRE check after the holder committed.
            for attempt in attempts.values():
                if attempt.state == "busy":
                    attempt.emit("fresh_retry")
                    attempt.check()
                    if attempt.state == "busy":
                        raise AssertionError("bounded schedule failed to release writer")
                    attempt.finish()
            rows = [{"id": row[0], "cents": row[1]} for row in conns[0].execute(
                "SELECT id,cents FROM reservations ORDER BY id").fetchall()]
            committed = total(conns[0])
            return {"mode": mode, "schedule": list(schedule), "costs_cents": list(costs),
                    "initial_cents": initial, "cap_cents": CAP, "total_cents": committed,
                    "over_cap": committed > CAP, "rows": rows,
                    "outcomes": {k: v.state for k, v in attempts.items()}, "trace": trace}
        finally:
            for conn in conns:
                conn.close()


def build_run():
    cases = []
    for fixture in FIXTURES:
        for mode in MODES:
            for schedule in schedules():
                cases.append({"fixture": fixture["id"], **run_case(
                    fixture["costs"], mode, schedule, fixture["initial"])})
    counts = []
    for fixture in FIXTURES:
        for mode in MODES:
            selected = [c for c in cases if c["fixture"] == fixture["id"] and c["mode"] == mode]
            counts.append({"fixture": fixture["id"], "mode": mode, "schedules": len(selected),
                           "over_cap_schedules": sum(c["over_cap"] for c in selected),
                           "totals_cents": sorted(set(c["total_cents"] for c in selected))})
    return {"schema_version": 1, "kind": "synthetic_two_connection_sqlite_reservations",
            "scope": "No model, bot, checkout or payment. Schedules are not probabilities.",
            "bucket": list(BUCKET), "fixture_count": len(FIXTURES), "case_count": len(cases),
            "counts": counts, "cases": cases}


def write_artifacts(root=None):
    root = Path(root) if root else Path(__file__).resolve().parent
    run = build_run()
    (root / "artifacts").mkdir(exist_ok=True)
    (root / "artifacts/run.json").write_text(json.dumps(run, indent=2) + "\n")
    lines = ["# Evidence summary", "", "Actual SQLite reservation rows, fictional integer cents.",
             "Six exhaustive order-preserving requested schedules per fixture and mode; not race probabilities.",
             "", "| Fixture | Mode | Over cap / schedules | Committed totals (cents) |",
             "|---|---|---:|---|"]
    for row in run["counts"]:
        lines.append(f'| {row["fixture"]} | {row["mode"]} | {row["over_cap_schedules"]}/{row["schedules"]} | {row["totals_cents"]} |')
    witness = ["A.check", "B.check", "A.finish", "B.finish"]
    for mode in MODES:
        case = next(c for c in run["cases"] if c["fixture"] == "overlapping_60_60"
                    and c["mode"] == mode and c["schedule"] == witness)
        lines += ["", "## Paired trace: " + mode, "", "```json", json.dumps(case, indent=2), "```"]
    lines += ["", "## Limits", "", "The record is a reservation, not money spent. The source bot was not run.",
              "The host must choose the correct shared budget key and trusted price. This tests one SQLite database",
              "and bounded schedules, not distributed checkout, crash recovery, refunds, fairness or live-model behavior."]
    (root / "evidence.md").write_text("\n".join(lines) + "\n")
    return run


if __name__ == "__main__":
    result = write_artifacts()
    print(json.dumps({"case_count": result["case_count"], "counts": result["counts"]}, indent=2))
