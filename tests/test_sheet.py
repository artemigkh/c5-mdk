"""Contact-sheet smoke test: run Continents at duel size for 2 seeds through host/sheet.py and check the
sheet PNG and summary.json.  Run: python tests/test_sheet.py  (or pytest tests/test_sheet.py)

Outputs go to out/_test_sheet/ (gitignored).
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out", "_test_sheet")


def test_sheet_two_seeds():
    png = os.path.join(OUT, "continents_duel.png")
    summary = os.path.join(OUT, "continents_duel", "summary.json")
    for p in (png, summary):
        if os.path.exists(p):
            os.remove(p)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "host", "sheet.py"), "Continents", "--size", "duel",
                        "--seeds", "1,2", "--layer", "mask", "--tile-w", "400", "--workers", "2", "--out", png],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.path.exists(png) and os.path.exists(summary)
    from PIL import Image
    with Image.open(png) as im:
        assert im.width > 2 * 400 and im.height > 200, im.size
    with open(summary, encoding="utf-8") as f:
        s = json.load(f)
    runs = s["runs"]
    assert len(runs) == 2 and all(e["ok"] for e in runs), runs
    assert sorted(e["seed"] for e in runs) == [1, 2]
    for e in runs:
        assert 0 < e["metrics"]["land_pct"] < 100
        assert os.path.exists(os.path.join(ROOT, e["png"]))


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                import traceback
                traceback.print_exc()
                print("FAIL", name, e)
    sys.exit(1 if fails else 0)
