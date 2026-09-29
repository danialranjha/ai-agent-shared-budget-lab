"""Run focused checks and two deliberate regressions; writes technical evidence only."""
import io
import json
from pathlib import Path
import unittest
import experiment as lab

ROOT = Path(__file__).resolve().parent


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    names = []
    def collect(group):
        for test in group:
            if isinstance(test, unittest.TestSuite):
                collect(test)
            else:
                names.append(test.id())
    collect(suite)
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    tests = {"tests_run": result.testsRun, "passed": result.wasSuccessful(), "test_ids": names,
             "failures": len(result.failures), "errors": len(result.errors)}
    # Functional mutation of the intervention: remove its transaction scope,
    # retaining the same cost check and insertion. This is the control path.
    unlocked = [lab.run_case((6000, 6000), "separate_check", s) for s in lab.schedules()]
    strict = [lab.run_case((4000, 6000), "atomic_reservation", s, strict=True) for s in lab.schedules()]
    mutations = [
        {"mutation": "remove_check_through_commit_transaction", "detected": any(r["over_cap"] for r in unlocked),
         "invariant_failures": sum(r["over_cap"] for r in unlocked), "schedules": 6},
        {"mutation": "replace_less_equal_with_strict_less", "detected": any(r["total_cents"] != 10000 for r in strict),
         "benign_exact_fill_failures": sum(r["total_cents"] != 10000 for r in strict), "schedules": 6},
    ]
    (ROOT / "artifacts").mkdir(exist_ok=True)
    for name, data in (("tests.json", tests), ("mutations.json", mutations)):
        (ROOT / "artifacts" / name).write_text(json.dumps(data, indent=2) + "\n")
    print(output.getvalue())
    print(json.dumps(mutations, indent=2))
    return 0 if result.wasSuccessful() and all(m["detected"] for m in mutations) else 1


if __name__ == "__main__":
    raise SystemExit(main())
