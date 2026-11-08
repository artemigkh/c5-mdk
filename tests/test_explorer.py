"""Explorer smoke test: run Continents at duel size for 2 seeds through host/sheet.py --explorer and check
explorer.html, the per-run terrain / resources PNGs and the embedded metadata.
Run: python tests/test_explorer.py  (or pytest tests/test_explorer.py)

Outputs go to out/_test_explorer/ (gitignored).
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out", "_test_explorer")


def test_sheet_explorer_two_seeds():
    png = os.path.join(OUT, "continents_duel.png")
    work = os.path.join(OUT, "continents_duel")
    exp = os.path.join(work, "explorer")
    if os.path.exists(exp):
        shutil.rmtree(exp)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "host", "sheet.py"), "Continents", "--size", "duel",
                        "--seeds", "1,2", "--tile-w", "300", "--workers", "2", "--out", png, "--explorer"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    html_path = os.path.join(exp, "explorer.html")
    assert os.path.exists(html_path), r.stdout + r.stderr
    with open(os.path.join(work, "summary.json"), encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["layer"] == "mask"                     # contact sheets default to shape only
    with open(html_path, encoding="utf-8") as f:
        page = f.read()
    m = re.search(r"<script>const DATA = (.*?);</script>", page, re.S)
    assert m, "embedded DATA object missing"
    data = json.loads(m.group(1))
    labels = [e["label"] for e in summary["runs"]]
    assert [e["label"] for e in data["maps"]] == labels   # summary order kept
    for e in data["maps"]:
        assert e["label"] in page
        assert e["ok"], e.get("error")
        for layer in ("terrain", "resources"):
            assert os.path.exists(os.path.join(exp, e["img"][layer])), e["img"][layer]
            assert e["img"][layer] in page
        assert e["exp_majors"] == 2 and e["exp_cs"] == 4, e   # duel: 2 civs, 4 city-states (log header)
        assert e["majors"] == 2 and 0 <= e["cs"] <= 4
        assert 0 < e["metrics"]["land_pct"] < 100
        for layer in ("terrain", "resources"):           # text comes as overlay label records
            L = e["labels"][layer]
            assert L["w"] > 0 and L["h"] > 0 and set(L["font"]) == set(data["label_kinds"])
            assert L["items"], layer
            x, y, k, txt = L["items"][0]
            assert 0 <= x <= L["w"] and 0 <= y <= L["h"] and txt and 0 <= k < len(data["label_kinds"])
        civs = [it for it in e["labels"]["terrain"]["items"] if data["label_kinds"][it[2]] == "civ"]
        assert len(civs) >= 2                            # one name per placed major (duel: 2)
    assert '<svg id="ov"' in page and "pointer-events:none" in page    # overlay built by the page script
    assert all(data["label_style"][k]["min"] > 0 for k in data["label_kinds"])


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
