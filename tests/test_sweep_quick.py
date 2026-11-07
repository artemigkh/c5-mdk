"""Quick sweep regression test (< 60 s): the reference scripts at duel size through tests/sweep.run_job
(c5gen subprocess + validate_dump), plus one WorldBuilder detection, one team-mode script and one known
VP-incompatible vanilla script that must keep failing with its script-side error (not a harness error).

Run: python tests/test_sweep_quick.py   (or pytest tests/test_sweep_quick.py)
"""
import multiprocessing
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep  # noqa: E402


def _jobs():
    specs = {s: p for s, _, _, p in sweep.script_specs()}
    jobs = []

    def add(spec, seed=1, extra=(), size="duel"):
        if spec not in specs:
            return
        jobs.append({"spec": spec, "path": specs[spec], "size": size, "seed": seed, "areas": "literal",
                     "png": False, "unsupported": sweep.worldbuilder_reason(specs[spec]), "timeout": 120,
                     "extra": list(extra), "validate": True, "tag": "quick"})
    for spec in sweep.REFERENCE:
        add(spec)
    add("exp1:Hemispheres", extra=("--teams", "2"))
    add("dlc-sp2:WB_Script_Random_Earth")
    add("assets:Lakes")
    return jobs


def run_all(workers=8):
    t0 = time.perf_counter()
    jobs = _jobs()
    with multiprocessing.Pool(workers) as pool:
        recs = pool.map(sweep.run_job, jobs)
    return {r["spec"]: r for r in recs}, time.perf_counter() - t0


def test_sweep_quick():
    recs, secs = run_all()
    bad = []
    for spec in sweep.REFERENCE:
        if spec in recs and recs[spec]["status"] != "ok":
            bad.append("%s: %s %s" % (spec, recs[spec]["status"], recs[spec].get("error_line", "")))
    assert not bad, "\n".join(bad)
    if "exp1:Hemispheres" in recs:
        assert recs["exp1:Hemispheres"]["status"] == "ok", recs["exp1:Hemispheres"].get("error_line")
    if "dlc-sp2:WB_Script_Random_Earth" in recs:
        assert recs["dlc-sp2:WB_Script_Random_Earth"]["status"] == "unsupported"
    if "assets:Lakes" in recs:
        r = recs["assets:Lakes"]
        assert r["status"] == "error" and "cityStateData" in r.get("error", ""), r
    for r in recs.values():
        if r["status"] == "ok":
            st = r["stats"]
            assert st["majors"] == 2 and st["starts"] >= 3, (r["spec"], st)
            assert st["resources"] > 20 and st["land_pct"] > 5, (r["spec"], st)
    assert secs < 60, "quick sweep took %.1fs" % secs
    return recs, secs


if __name__ == "__main__":
    try:
        recs, secs = test_sweep_quick()
        for spec, r in sorted(recs.items()):
            print("  %-34s %-11s %5.1fs" % (spec, r["status"], r.get("seconds", 0)))
        print("PASS test_sweep_quick (%.1fs)" % secs)
        sys.exit(0)
    except AssertionError as e:
        print("FAIL test_sweep_quick", e)
        sys.exit(1)
