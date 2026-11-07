"""Regression: the engine's default (literal) area algorithm must reproduce the real VP DLL's areas.

The fixture is a plot/area dump from a real headless game (civ5-headless, VP 5.4.8 DLL, stock
Assets/Maps/Pangaea.lua, standard size, map seed 4242) taken with tests/probes/dump-areas.lua.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import compare_areas  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "real_pangaea_standard_seed4242.json")


def main():
    out = compare_areas.main(FIXTURE)
    lit, ff = out["literal"], out["floodfill"]
    ok = True
    for key in ("rand_index", "landmass_rand_index", "impassable_match", "lake_match"):
        if abs(lit[key] - 1.0) > 1e-12:
            print("FAIL literal %s = %s (expected 1.0)" % (key, lit[key]))
            ok = False
    if lit["real_areas"] != lit["harness_areas"]:
        print("FAIL literal area count %s != real %s" % (lit["harness_areas"], lit["real_areas"]))
        ok = False
    if ff["rand_index"] >= 1.0:
        print("FAIL floodfill unexpectedly matches the real DLL too; the fixture no longer discriminates")
        ok = False
    print("PASS test_areas_real: literal areas match the real DLL exactly; floodfill rand index %.3f" % ff["rand_index"] if ok else "test_areas_real FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
