import sqlite3
import tempfile
import unittest
from pathlib import Path
import experiment as lab

WITNESS = ("A.check", "B.check", "A.finish", "B.finish")


class BudgetTests(unittest.TestCase):
    def test_six_schedules_unique_and_ordered(self):
        rows = lab.schedules()
        self.assertEqual(len(set(rows)), 6)
        for row in rows:
            for name in "AB":
                self.assertLess(row.index(name + ".check"), row.index(name + ".finish"))

    def test_actual_stale_read_witness(self):
        row = lab.run_case((6000, 6000), "separate_check", WITNESS)
        self.assertEqual(row["rows"], [{"id": "A", "cents": 6000}, {"id": "B", "cents": 6000}])
        self.assertEqual([e["seen_cents"] for e in row["trace"] if e["event"] == "read_and_check"], [0, 0])
        self.assertEqual(row["total_cents"], 12000)

    def test_atomic_contention_rechecks_current_balance(self):
        row = lab.run_case((6000, 6000), "atomic_reservation", WITNESS)
        events = [e["event"] for e in row["trace"]]
        self.assertIn("busy_no_decision", events)
        self.assertLess(events.index("reservation_committed"), events.index("fresh_retry"))
        self.assertEqual([e["seen_cents"] for e in row["trace"] if e["event"] == "read_and_check"], [0, 6000])
        self.assertEqual(row["outcomes"], {"A": "reserved", "B": "refused"})
        self.assertEqual(row["rows"], [{"id": "A", "cents": 6000}])

    def test_all_primary_schedules(self):
        for mode, expected in (("separate_check", 4), ("atomic_reservation", 0)):
            rows = [lab.run_case((6000, 6000), mode, s) for s in lab.schedules()]
            self.assertEqual(sum(r["over_cap"] for r in rows), expected)

    def test_benign_exact_fill_both_orders_preserved(self):
        for mode in lab.MODES:
            for s in lab.schedules():
                row = lab.run_case((4000, 6000), mode, s)
                self.assertEqual(row["total_cents"], 10000)
                self.assertEqual(row["outcomes"], {"A": "reserved", "B": "reserved"})

    def test_prior_balance_counted(self):
        for s in lab.schedules():
            row = lab.run_case((5000, 5000), "atomic_reservation", s, 2000)
            self.assertEqual(row["total_cents"], 7000)
            self.assertIn({"id": "prior", "cents": 2000}, row["rows"])

    def test_large_request_refused_small_twin_works(self):
        for mode in lab.MODES:
            row = lab.run_case((11000, 2000), mode, WITNESS)
            self.assertEqual(row["outcomes"], {"A": "refused", "B": "reserved"})
            self.assertEqual(row["total_cents"], 2000)

    def test_invalid_amounts_cannot_reduce_ledger(self):
        for bad in (0, -1, True, 1.5, "6000", None, 10**9+1):
            for mode in lab.MODES:
                row = lab.run_case((bad, 2000), mode, WITNESS)
                self.assertEqual(row["outcomes"], {"A": "invalid", "B": "reserved"})
                self.assertEqual(row["total_cents"], 2000)

    def test_sqlite_itself_blocks_second_writer(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = lab.connect(Path(d)/"x.db"), lab.connect(Path(d)/"x.db")
            try:
                lab.initialize(a)
                a.execute("BEGIN IMMEDIATE")
                with self.assertRaises(sqlite3.OperationalError) as got:
                    b.execute("BEGIN IMMEDIATE")
                self.assertEqual(got.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY)
                self.assertFalse(b.in_transaction)
                a.execute("ROLLBACK")
                b.execute("BEGIN IMMEDIATE")
                b.execute("ROLLBACK")
            finally:
                a.close(); b.close()

    def test_budget_key_is_a_trusted_scope_limit(self):
        c = sqlite3.connect(":memory:")
        try:
            lab.initialize(c)
            c.execute("INSERT INTO reservations VALUES (?,?,?,?)", ("x", "other-owner", "day-demo", 6000))
            self.assertEqual(lab.total(c), 0)
            self.assertEqual(lab.total(c, ("other-owner", "day-demo")), 6000)
        finally:
            c.close()

    def test_complete_fixture_invariant_and_determinism(self):
        first, second = lab.build_run(), lab.build_run()
        self.assertEqual(first, second)
        self.assertEqual(first["case_count"], 60)
        for row in first["cases"]:
            self.assertEqual(row["total_cents"], sum(x["cents"] for x in row["rows"]))
            if row["mode"] == "atomic_reservation":
                self.assertLessEqual(row["total_cents"], lab.CAP)

    def test_invalid_scheduler_input_rejected(self):
        with self.assertRaises(ValueError):
            lab.run_case((1, 2), "unknown", WITNESS)
        with self.assertRaises(ValueError):
            lab.run_case((1, 2), "atomic_reservation", tuple(reversed(WITNESS)))


if __name__ == "__main__":
    unittest.main()
