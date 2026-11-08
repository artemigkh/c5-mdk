#!/usr/bin/env python3
"""Map explorer: review starts, city-states and resources ONE map at a time in an interactive HTML page.

    python host/explorer.py --runs out/Crescent/sheets/r9_default16_standard
    python host/explorer.py out/Continents/Continents_standard_1.json out/MyMap/run2/ --out out/review
    python host/explorer.py --runs out/sheets/mymap_large_seed1 --embed      # one-file handoff
    python host/sheet.py MyMap.lua --seeds 1,2,3,4 --explorer                # sheet + explorer in one go

Contact sheets (host/sheet.py) are for shape; this page is for everything a grid hides at tile scale.
Inputs: --runs DIR (a sheet work folder: runs/<label>/ each holding one dump *.json + .log, plus
summary.json whose run order and labels are kept), and/or explicit dump paths (or folders holding one
dump).  For every dump it renders, next to the page, <key>_terrain.png and <key>_resources.png (full
size, start-plot / city-state markers and resource dots but NO text; PNGs newer than both their dump and
render/render_map.py are kept unless --force).  All text (civ / city-state names, player ids, resource
and natural-wonder labels) is drawn by the page as an SVG overlay from render_map.label_records(), so it
stays sharp at every zoom; a label class whose on-screen font size would fall below LABEL_MIN_PX
(resources first, then city-states, then civ names) is hidden, leaving only its marker / dot,
computes host/metrics.py metrics, counts placed majors / city-states against the expected numbers
(the "# civs:" / "# city-states:" header of the c5gen .log, else the Worlds defaults) and greps the
log for parameter lines (--grep, default "\\[\\w+\\] params|\\[\\w+\\] fit").

Output: <out>/explorer.html (default <runs>/explorer/), self-contained (inline CSS/JS, metadata
embedded as a JS object so it works from file://).  Keys: <-/-> previous/next map, 1/2 terrain /
resources layer, z toggle zoom; click or wheel on the map zooms 1x (fit width) / 2x, drag to pan.
"""
import argparse
import base64
import concurrent.futures as cf
import glob
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "render"))
sys.path.insert(0, HERE)

DEFAULT_GREP = r"\[\w+\] params|\[\w+\] fit"
LAYERS = ("terrain", "resources")
TARGET_W = 2000          # rendered PNG width target (px); render_map's default hex size aims here too
MAX_GREP_LINES = 12
# Overlay label classes are hidden when their font would be smaller than this on screen (CSS px).
LABEL_MIN_PX = {"res": 9, "cs": 9, "wonder": 9, "civ": 8, "num": 7}
LABEL_NAMES = {"civ": "civs", "cs": "city-states", "num": "player ids", "res": "resources", "wonder": "wonders"}

# Worlds table defaults (DefaultPlayers, DefaultMinorCivs) of the VP DB, used only when the c5gen log
# header ("# civs:" / "# city-states:") is missing.  Matches `SELECT ... FROM Worlds` as of 2026-11.
WORLD_DEFAULTS = {"WORLDSIZE_DUEL": (2, 4), "WORLDSIZE_TINY": (4, 8), "WORLDSIZE_SMALL": (6, 12),
                  "WORLDSIZE_STANDARD": (8, 16), "WORLDSIZE_LARGE": (10, 20), "WORLDSIZE_HUGE": (12, 24)}

# Metrics shown in the caption table (the rest go into the collapsible "all metrics" block).
HEADLINE = ["land_pct", "landmasses_30", "largest_landmass_pct", "majors", "city_states",
            "cap_nn_mean", "cap_nn_min", "cap_cs_mean", "cap_cs_min", "cs_nn_min", "cs_cap_min",
            "cap_coastal_pct", "cap_land_r3_min", "cap_lux_r3_mean", "cap_strat_r3_mean",
            "luxury_per100", "strategic_per100", "bonus_per100", "bad_starts"]


def safe_name(s):
    return re.sub(r"[^\w.=+-]+", "_", s).strip("_") or "map"


# ================================================================================================
# Collecting inputs
# ================================================================================================
def _dump_in(folder):
    found = [p for p in glob.glob(os.path.join(folder, "*.json")) if os.path.basename(p) != "cmd.json"]
    return found[0] if len(found) == 1 else None


def _resolve(p):
    """Stored paths in summary.json are relative to the repo root; accept absolute / cwd-relative too."""
    for cand in (p, os.path.join(ROOT, p)):
        if cand and os.path.exists(cand):
            return os.path.abspath(cand)
    return None


def collect(runs_dirs, dumps):
    """List of entries {label, seed, args, dump (abs path or None), error, summary_grep, warnings}."""
    entries = []
    for rd in runs_dirs or []:
        rd = os.path.abspath(rd)
        summ = os.path.join(rd, "summary.json")
        if os.path.exists(summ):
            with open(summ, encoding="utf-8") as f:
                s = json.load(f)
            for r in s.get("runs") or []:
                dump = _resolve(r.get("dump")) if r.get("dump") else None
                if not dump and r.get("key"):
                    dump = _dump_in(os.path.join(rd, "runs", r["key"]))
                entries.append({"label": r.get("label") or r.get("key") or "?", "seed": r.get("seed"),
                                "args": list(r.get("args") or []),     # sheet runs: includes --common
                                "dump": dump, "error": None if dump else (r.get("error") or "no dump"),
                                "summary_grep": r.get("grep") or [], "warnings": r.get("warnings")})
        else:
            sub = sorted(glob.glob(os.path.join(rd, "runs", "*"))) or sorted(glob.glob(os.path.join(rd, "*")))
            for d in sub:
                dump = _dump_in(d) if os.path.isdir(d) else None
                if dump:
                    entries.append({"label": os.path.basename(d), "seed": None, "args": [], "dump": dump})
    for p in dumps or []:
        dump = _dump_in(p) if os.path.isdir(p) else (os.path.abspath(p) if os.path.exists(p) else None)
        if not dump:
            raise SystemExit(f"explorer: no single dump found at {p}")
        entries.append({"label": os.path.splitext(os.path.basename(dump))[0], "seed": None, "args": [],
                        "dump": dump})
    seen = {}
    for e in entries:
        k = safe_name(e["label"])
        seen[k] = seen.get(k, 0) + 1
        e["key"] = k if seen[k] == 1 else f"{k}_{seen[k]}"
    return entries


# ================================================================================================
# Per-map work (worker process: rendering is pure Python and GIL-bound)
# ================================================================================================
def grep_lines(path, pattern, limit=MAX_GREP_LINES):
    if not pattern or not path or not os.path.exists(path):
        return []
    rx, out = re.compile(pattern), []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = rx.search(line)
            if m:
                s = " ".join(line[m.start():].split())
                if s not in out:
                    out.append(s)
                if len(out) >= limit:
                    break
    return out


def log_header(path):
    """(civs, city_states) lists from the c5gen log header, or (None, None)."""
    civs = cs = None
    if path and os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if line.startswith("# civs:"):
                    civs = [x for x in line[7:].strip().split(", ") if x]
                elif line.startswith("# city-states:"):
                    cs = [x for x in line[14:].strip().split(", ") if x]
                if (civs is not None and cs is not None) or i > 40:
                    break
    return civs, cs


def process(job):
    """Render the two layers and gather metadata for one dump.  Returns a JSON-able dict."""
    import metrics
    import render_map
    e = {k: job[k] for k in ("key", "label", "seed", "args")}
    try:
        with open(job["dump"], encoding="utf-8") as f:
            raw = json.load(f)
        m = metrics.compute_metrics(raw)
        d = render_map.normalize_dump(raw)
        W = d["width"]
        cols = W + (0 if d.get("wrap_x") else 0.5)
        hex_size = max(4.0, min(40.0, TARGET_W / (3 ** 0.5 * cols)))
        newest = max(os.path.getmtime(job["dump"]), os.path.getmtime(render_map.__file__))
        kinds = render_map.LABEL_KINDS
        labels = {}
        for layer in LAYERS:
            png = os.path.join(job["out"], f"{job['key']}_{layer}.png")
            if job["force"] or not os.path.exists(png) or os.path.getmtime(png) < newest:
                # markers and dots only; the text comes from label_records() as a vector overlay
                render_map.render_png(d, png, hex_size=hex_size, layer=layer, legend=False, title=False,
                                      labels=False, starts=True, text=False, grid=True, ss=2)
            rec = render_map.label_records(d, hex_size=hex_size, layer=layer, labels=True, starts=True, ss=2)
            labels[layer] = {"w": rec["width"], "h": rec["height"], "font": rec["font"],
                             "items": [[r["x_px"], r["y_px"], kinds.index(r["kind"]), r["text"]]
                                       for r in rec["labels"]]}
        sp = raw.get("start_plots") or []
        log = os.path.splitext(job["dump"])[0] + ".log"
        civs, cs = log_header(log)
        dflt = WORLD_DEFAULTS.get(raw.get("world_size"), (None, None))
        exp_maj = len(raw["civs"]) if isinstance(raw.get("civs"), list) else (len(civs) if civs is not None else dflt[0])
        exp_cs = len(raw["minors"]) if isinstance(raw.get("minors"), list) else (len(cs) if cs is not None else dflt[1])
        placed = [s for s in sp if 0 <= s.get("x", -1) < W and 0 <= s.get("y", -1) < d["height"]]
        e.update(
            ok=True, map=f"{W}x{d['height']}", world=raw.get("world_size"), script=raw.get("script"),
            dump_seed=raw.get("seed"), wrap_x=bool(raw.get("wrap_x")),
            majors=sum(1 for s in placed if not s.get("minor")),
            cs=sum(1 for s in placed if s.get("minor")),
            exp_majors=exp_maj, exp_cs=exp_cs,
            expected_from="log" if civs is not None else "Worlds default",
            grep=grep_lines(log, job["grep"]) if os.path.exists(log) else list(job.get("summary_grep") or []),
            warnings=job.get("warnings") if job.get("warnings") is not None else
            [w.split("WARNING: ", 1)[1] for w in grep_lines(log, r"\[c5maps\] WARNING: ", 50)],
            metrics={k: (round(v, 2) if isinstance(v, float) else v) for k, v in m.items()
                     if k in metrics.METRIC_INFO},
            dump=os.path.relpath(job["dump"], ROOT),
            img={layer: f"{job['key']}_{layer}.png" for layer in LAYERS},
            labels=labels)   # per layer: image size, font px per kind, [x, y, kind index, text] (image px)
        if e["seed"] is None:
            e["seed"] = raw.get("seed")
    except Exception:  # keep going; the page shows the error for this map
        import traceback
        e.update(ok=False, error=traceback.format_exc()[-2000:])
    return e


# ================================================================================================
# Page
# ================================================================================================
CSS = r"""
:root{--bg:#f6f6f3;--panel:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#ddddd6;--acc:#2f5f8a;--bad:#c62828;--map:#121417}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:14px/1.4 system-ui,Segoe UI,Arial,sans-serif}
#app{display:grid;grid-template-columns:260px 1fr;height:100vh}
#side{border-right:1px solid var(--line);background:var(--panel);overflow:auto}
#side h1{font-size:15px;margin:12px 12px 4px}
#side .sub{color:var(--mute);font-size:12px;margin:0 12px 8px}
#list{list-style:none;margin:0;padding:0}
#list li{padding:6px 12px;border-top:1px solid var(--line);cursor:pointer;display:flex;justify-content:space-between;gap:8px}
#list li:hover{background:#eef2f6}
#list li.cur{background:#dfe8f1;font-weight:600}
#list .m{color:var(--mute);font-size:12px;white-space:nowrap;font-variant-numeric:tabular-nums}
.bad{color:var(--bad)!important;font-weight:600}
#main{display:flex;flex-direction:column;min-width:0;overflow:auto}
#bar{display:flex;gap:8px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--line);background:var(--panel);position:sticky;top:0;z-index:2;flex-wrap:wrap}
#bar button{font:inherit;padding:4px 10px;border:1px solid var(--line);background:#fafaf8;border-radius:4px;cursor:pointer}
#bar button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
#bar select{font:inherit;padding:3px;max-width:320px}
#title{font-weight:600;font-size:16px;margin-left:6px}
#bar .hint{margin-left:auto;color:var(--mute);font-size:12px}
#lbl{color:var(--mute);font-size:12px;margin-left:12px}
#view{flex:none;background:var(--map);overflow:hidden;position:relative;cursor:zoom-in;user-select:none}
#view.z2{cursor:grab}
#view.drag{cursor:grabbing}
#stage{position:relative;width:100%}
#stage img{display:block;width:100%;height:auto;-webkit-user-drag:none}
#stage.loading #ov{visibility:hidden}
#ov{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;overflow:hidden}
#ov text{text-anchor:middle;dominant-baseline:central;paint-order:stroke;stroke-linejoin:round;font-family:system-ui,Segoe UI,Arial,sans-serif}
#ov.h-civ .k-civ,#ov.h-cs .k-cs,#ov.h-num .k-num,#ov.h-res .k-res,#ov.h-wonder .k-wonder{display:none}
#view .fail{color:#fff;background:var(--bad);padding:16px;white-space:pre-wrap;font:12px/1.4 Consolas,monospace}
#cap{display:grid;grid-template-columns:minmax(260px,1fr) minmax(320px,1.2fr);gap:16px;padding:12px}
#cap section{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px}
#cap h2{font-size:13px;margin:0 0 6px;color:var(--mute);text-transform:uppercase;letter-spacing:.04em}
#cap code,#cap pre{font:12px/1.45 Consolas,monospace}
#cap pre{margin:0;white-space:pre-wrap;word-break:break-word}
table{border-collapse:collapse;width:100%}
td{padding:2px 6px;border-bottom:1px solid #eee;vertical-align:top}
td.v{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
details summary{cursor:pointer;color:var(--acc);margin-top:8px}
.warn{color:#b35c00}
@media (max-width:800px){#app{grid-template-columns:1fr}#side{display:none}#cap{grid-template-columns:1fr}}
"""

JS = r"""
(function(){
const D = DATA, maps = D.maps, info = D.metric_info;
const $ = id => document.getElementById(id);
let cur = 0, layer = "terrain", zoom = 1;
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmt = (v, u) => v == null ? "–" : (typeof v === "number" && !Number.isInteger(v) ? v.toFixed(u === "%" || u === "lat" ? 1 : 2) : String(v));
const short = m => m.ok ? (m.metrics.land_pct == null ? "?" : m.metrics.land_pct.toFixed(1) + "%") : "FAIL";
const csBad = m => m.ok && m.exp_cs != null && m.cs < m.exp_cs;
const majBad = m => m.ok && m.exp_majors != null && m.majors < m.exp_majors;
const src = (m, l) => (D.embedded && D.embedded[m.key + "_" + l]) || m.img[l];
const KINDS = D.label_kinds, LST = D.label_style;

function buildList(){
  const ul = $("list"), sel = $("sel");
  maps.forEach((m, i) => {
    const li = document.createElement("li");
    const cs = m.ok ? `<span class="${csBad(m) ? "bad" : ""}">CS ${m.cs}/${m.exp_cs == null ? "?" : m.exp_cs}</span>` : `<span class="bad">failed</span>`;
    li.innerHTML = `<span>${esc(m.label)}</span><span class="m">${short(m)} · ${cs}</span>`;
    li.onclick = () => show(i);
    ul.appendChild(li);
    const o = document.createElement("option");
    o.value = i;
    o.textContent = `${m.label} — ${short(m)}` + (m.ok ? ` — CS ${m.cs}/${m.exp_cs == null ? "?" : m.exp_cs}${csBad(m) ? " (short)" : ""}` : "");
    sel.appendChild(o);
  });
  sel.onchange = () => show(+sel.value);
}

function row(k, m){
  const i = info[k] || {label: k, unit: ""};
  let cls = "";
  if (k === "city_states" && csBad(m)) cls = "bad";
  if (k === "majors" && majBad(m)) cls = "bad";
  if (k === "bad_starts" && m.metrics[k] > 0) cls = "bad";
  return `<tr><td>${esc(i.label)}</td><td class="v ${cls}">${fmt(m.metrics[k], i.unit)}${i.unit && i.unit !== "n" ? " " + esc(i.unit) : ""}</td></tr>`;
}

function caption(m){
  if (!m.ok) return `<section><h2>Error</h2><pre>${esc(m.error)}</pre></section>`;
  const exp = (n, e) => e == null ? n : `${n} / ${e}`;
  let h = `<section><h2>Run</h2><table>
    <tr><td>Seed</td><td class="v">${esc(m.seed)}</td></tr>
    <tr><td>Map</td><td class="v">${esc(m.map)} ${esc((m.world || "").replace("WORLDSIZE_", "").toLowerCase())}${m.wrap_x ? " · wrapX" : ""}</td></tr>
    <tr><td>Majors placed / expected</td><td class="v ${majBad(m) ? "bad" : ""}">${exp(m.majors, m.exp_majors)}</td></tr>
    <tr><td>City-states placed / expected</td><td class="v ${csBad(m) ? "bad" : ""}">${exp(m.cs, m.exp_cs)}${csBad(m) ? " — short " + (m.exp_cs - m.cs) : ""}</td></tr>
    <tr><td>Script</td><td class="v">${esc(m.script)}</td></tr></table>
    <h2 style="margin-top:10px">Dump</h2><pre>${esc(m.dump)}</pre>
    <h2 style="margin-top:10px">Args</h2><pre>${esc((m.args || []).join(" ") || "(none)")}</pre>`;
  if (m.grep && m.grep.length) h += `<h2 style="margin-top:10px">Log</h2><pre>${m.grep.map(esc).join("\n")}</pre>`;
  if (m.warnings && m.warnings.length) h += `<h2 style="margin-top:10px">Warnings</h2><pre class="warn">${m.warnings.map(esc).join("\n")}</pre>`;
  h += `<p style="color:var(--mute);font-size:12px;margin:8px 0 0">Expected counts from ${esc(m.expected_from)}.</p></section>`;
  const shown = D.headline.filter(k => k in m.metrics);
  h += `<section><h2>Metrics</h2><table>${shown.map(k => row(k, m)).join("")}</table>`;
  let groups = {};
  Object.keys(m.metrics).filter(k => !shown.includes(k) && info[k]).forEach(k => (groups[info[k].group] = groups[info[k].group] || []).push(k));
  h += `<details><summary>All metrics</summary>` + Object.keys(groups).map(g =>
    `<h2 style="margin-top:10px">${esc(g)}</h2><table>${groups[g].map(k => row(k, m)).join("")}</table>`).join("") + `</details></section>`;
  return h;
}

// Text overlay: one <svg> in image-pixel coordinates (viewBox = PNG size) stretched over the <img> inside
// the same #stage, so it scales, scrolls and pans with the image and is never rasterised.
function labelSvg(m, l){
  const L = m.labels && m.labels[l];
  if (!L) return "";
  const groups = KINDS.map(() => []);
  for (const it of L.items) groups[it[2]].push(`<text x="${it[0]}" y="${it[1]}">${esc(it[3])}</text>`);
  return `<svg id="ov" viewBox="0 0 ${L.w} ${L.h}" preserveAspectRatio="none" aria-hidden="true">` +
    KINDS.map((k, i) => {
      if (!groups[i].length) return "";
      const st = LST[k], fs = L.font[k];
      const stroke = st.halo ? `stroke="${st.halo}" stroke-width="${(fs * 0.3).toFixed(2)}"` : `stroke="none"`;
      return `<g class="k-${k}" font-size="${fs}" font-weight="${st.bold ? 700 : 400}" fill="${st.fill}" ${stroke}>${groups[i].join("")}</g>`;
    }).join("") + `</svg>`;
}

function fitLabels(){
  // hide a label class whose on-screen font size (image px x display scale) is below its minimum
  const m = maps[cur], ov = $("ov"), st = $("stage");
  if (!ov || !st || !m.ok || !m.labels) return;
  const L = m.labels[layer], k = st.clientWidth / L.w, shown = [];
  for (const kind of KINDS) {
    const hide = !(L.font[kind] * k >= LST[kind].min);
    ov.classList.toggle("h-" + kind, hide);
    if (!hide && L.items.some(it => KINDS[it[2]] === kind)) shown.push(LST[kind].name);
  }
  $("lbl").textContent = "text: " + (shown.length ? shown.join(", ") : "none (zoom in)");
}

function setZoom(z, cx, cy){
  // (cx, cy): client point that stays under the cursor; omitted = keep the current view centre
  const v = $("view"), img = v.querySelector("img"), st = $("stage");
  if (!img || !st) return;
  const r = v.getBoundingClientRect();
  const ox = cx == null ? v.clientWidth / 2 : cx - r.left, oy = cy == null ? v.clientHeight / 2 : cy - r.top;
  const fx = (ox + v.scrollLeft) / (img.clientWidth || 1), fy = (oy + v.scrollTop) / (img.clientHeight || 1);
  zoom = z;
  v.classList.toggle("z2", z === 2);
  st.style.width = (z * 100) + "%";
  if (z === 2) {
    v.style.height = Math.min(img.clientHeight / 2, window.innerHeight - $("bar").offsetHeight - 8) + "px";
    v.scrollLeft = fx * img.clientWidth - Math.min(ox, v.clientWidth);
    v.scrollTop = fy * img.clientHeight - Math.min(oy, v.clientHeight);
  } else { v.style.height = ""; v.scrollLeft = v.scrollTop = 0; }
  $("zbtn").textContent = z === 2 ? "Zoom 2×" : "Zoom 1×";
  fitLabels();
}

function render(){
  const m = maps[cur], v = $("view");
  if (m.ok) {
    // swap src on the same <img> so a 2x zoom keeps its scroll position across maps / layers
    let st = $("stage"), img = st && st.querySelector("img");
    if (!img) {
      v.innerHTML = `<div id="stage"><img></div>`;
      st = $("stage");
      img = st.querySelector("img");
      st.style.width = (zoom * 100) + "%";
      img.onload = () => { st.classList.remove("loading"); if (zoom === 2) setZoom(2); fitLabels(); };
      img.onerror = () => st.classList.remove("loading");
    }
    img.alt = m.label + " " + layer;
    const want = new URL(src(m, layer), location.href).href;
    if (img.src !== want) { st.classList.add("loading"); img.src = want; }  // labels wait for their image
    const old = $("ov");
    if (old) old.remove();
    st.insertAdjacentHTML("beforeend", labelSvg(m, layer));
    fitLabels();
  } else { v.innerHTML = `<div class="fail">FAILED ${esc(m.label)}\n\n${esc(m.error)}</div>`; v.style.height = ""; $("lbl").textContent = ""; }
  for (const l of ["terrain", "resources"]) $("b_" + l).classList.toggle("on", l === layer);
}

function show(i){
  cur = (i + maps.length) % maps.length;
  const m = maps[cur];
  $("title").innerHTML = `${esc(m.label)} <span style="color:var(--mute);font-weight:400">(${cur + 1}/${maps.length})</span>`;
  $("sel").value = cur;
  document.querySelectorAll("#list li").forEach((li, k) => li.classList.toggle("cur", k === cur));
  const li = document.querySelectorAll("#list li")[cur]; if (li) li.scrollIntoView({block: "nearest"});
  $("cap").innerHTML = caption(m);
  render();
  try { history.replaceState(null, "", "#" + encodeURIComponent(m.key)); } catch (e) {}
  [cur + 1, cur - 1].forEach(j => { const n = maps[(j + maps.length) % maps.length]; if (n.ok) (new Image()).src = src(n, layer); });
}

function setLayer(l){ layer = l; render(); }

// zoom + pan on the map
(function(){
  const v = $("view");
  let down = null, moved = false;
  v.addEventListener("mousedown", e => { if (e.button) return; down = {x: e.clientX, y: e.clientY, sl: v.scrollLeft, st: v.scrollTop}; moved = false; e.preventDefault(); });
  window.addEventListener("mousemove", e => {
    if (!down) return;
    const dx = e.clientX - down.x, dy = e.clientY - down.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
    if (moved && zoom === 2) { v.classList.add("drag"); v.scrollLeft = down.sl - dx; v.scrollTop = down.st - dy; }
  });
  window.addEventListener("mouseup", e => {
    if (!down) return;
    v.classList.remove("drag");
    if (!moved && e.target.closest && e.target.closest("#view")) setZoom(zoom === 1 ? 2 : 1, e.clientX, e.clientY);
    down = null;
  });
  v.addEventListener("wheel", e => {
    const want = e.deltaY < 0 ? 2 : 1;
    if (want !== zoom) { e.preventDefault(); setZoom(want, e.clientX, e.clientY); }
  }, {passive: false});
})();

document.addEventListener("keydown", e => {
  if (e.target.tagName === "SELECT" || e.altKey || e.ctrlKey || e.metaKey) return;
  if (e.key === "ArrowRight") { show(cur + 1); e.preventDefault(); }
  else if (e.key === "ArrowLeft") { show(cur - 1); e.preventDefault(); }
  else if (e.key === "1") setLayer("terrain");
  else if (e.key === "2") setLayer("resources");
  else if (e.key === "z" || e.key === "Z") setZoom(zoom === 1 ? 2 : 1);
});
$("prev").onclick = () => show(cur - 1);
$("next").onclick = () => show(cur + 1);
$("b_terrain").onclick = () => setLayer("terrain");
$("b_resources").onclick = () => setLayer("resources");
$("zbtn").onclick = () => setZoom(zoom === 1 ? 2 : 1);
window.addEventListener("resize", () => { if (zoom === 2) setZoom(2); else fitLabels(); });

buildList();
const h = decodeURIComponent((location.hash || "").slice(1));
const start = Math.max(0, maps.findIndex(m => m.key === h));
show(start);
})();
"""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{css}</style></head>
<body><div id="app">
<aside id="side"><h1>{title}</h1><div class="sub">{sub}</div><ul id="list"></ul></aside>
<main id="main">
<div id="bar">
<button id="prev" title="previous (&larr;)">&larr;</button><button id="next" title="next (&rarr;)">&rarr;</button>
<select id="sel" aria-label="map"></select>
<button id="b_terrain" title="key 1">Terrain</button><button id="b_resources" title="key 2">Resources</button>
<button id="zbtn" title="key z">Zoom 1&times;</button>
<span id="title"></span>
<span id="lbl" title="labels whose on-screen size would be too small are hidden; zoom in to show them"></span>
<span class="hint">&larr;/&rarr; map &middot; 1/2 layer &middot; click/wheel zoom &middot; drag to pan</span>
</div>
<div id="view"></div>
<div id="cap"></div>
</main></div>
<script>const DATA = {data};</script>
<script>{js}</script>
</body></html>
"""


def _js_json(obj):
    # safe inside <script>: no "</" sequences, no U+2028/9
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            .replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def build(runs_dirs=(), dumps=(), out=None, grep=DEFAULT_GREP, embed=False, force=False, workers=8,
          title=None, log=print):
    """Render PNGs, write explorer.html; return its path."""
    import metrics
    runs_dirs = [os.path.abspath(r) for r in (runs_dirs or [])]
    entries = collect(runs_dirs, dumps)
    if not entries:
        raise SystemExit("explorer: no maps found")
    if out is None:
        base = runs_dirs[0] if runs_dirs else os.path.dirname(os.path.dirname(os.path.abspath(entries[0]["dump"])))
        out = os.path.join(base, "explorer")
    out = os.path.abspath(out)
    os.makedirs(out, exist_ok=True)

    jobs = [dict(e, out=out, grep=grep, force=force) for e in entries if e.get("dump")]
    done = {}
    if jobs:
        with cf.ProcessPoolExecutor(max_workers=max(1, min(workers, len(jobs)))) as ex:
            futs = {ex.submit(process, j): j["key"] for j in jobs}
            for i, fut in enumerate(cf.as_completed(futs), 1):
                k = futs[fut]
                try:
                    done[k] = fut.result()
                except Exception as ex_:  # worker crash
                    j = next(j for j in jobs if j["key"] == k)
                    done[k] = {**{x: j[x] for x in ("key", "label", "seed", "args")}, "ok": False, "error": repr(ex_)}
                r = done[k]
                if r.get("ok"):
                    short = "" if r["exp_cs"] is None or r["cs"] >= r["exp_cs"] else "  << CS short"
                    log(f"[{i}/{len(jobs)}] {r['label']:<24} majors {r['majors']}/{r['exp_majors']}  "
                        f"CS {r['cs']}/{r['exp_cs']}{short}")
                else:
                    log(f"[{i}/{len(jobs)}] {r['label']:<24} FAILED")
    maps = []
    for e in entries:
        if e["key"] in done:
            maps.append(done[e["key"]])
        else:
            maps.append({"key": e["key"], "label": e["label"], "seed": e.get("seed"), "args": e.get("args") or [],
                         "ok": False, "error": e.get("error") or "no dump"})

    embedded = None
    if embed:
        embedded = {}
        for m in maps:
            for layer, rel in (m.get("img") or {}).items():
                with open(os.path.join(out, rel), "rb") as f:
                    embedded[f"{m['key']}_{layer}"] = "data:image/png;base64," + base64.b64encode(f.read()).decode()
    scripts = sorted({m.get("script") for m in maps if m.get("script")})
    worlds = sorted({(m.get("world") or "").replace("WORLDSIZE_", "").lower() for m in maps if m.get("world")})
    title = title or ("Explorer: " + (", ".join(scripts) or "maps"))
    n_short = sum(1 for m in maps if m.get("ok") and m["exp_cs"] is not None and m["cs"] < m["exp_cs"])
    sub = f"{len(maps)} map(s) · {', '.join(worlds)} · CS short on {n_short}"
    import render_map
    style = {k: {"fill": fill, "halo": halo, "bold": bold, "min": LABEL_MIN_PX[k], "name": LABEL_NAMES[k]}
             for k, (_, fill, halo, bold) in render_map.LABEL_STYLE.items()}
    data = {"maps": maps, "headline": HEADLINE, "embedded": embedded,
            "label_kinds": list(render_map.LABEL_KINDS), "label_style": style,
            "metric_info": {k: metrics.METRIC_INFO[k] for k in metrics.METRIC_KEYS}}
    page = PAGE.format(title=html.escape(title), sub=html.escape(sub), css=CSS, js=JS, data=_js_json(data))
    path = os.path.join(out, "explorer.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    log(f"wrote {os.path.relpath(path, ROOT)} ({len(maps)} maps, {len(page) / 1e6:.1f} MB"
        f"{', images embedded' if embed else ''}); CS short on {n_short}/{len(maps)}")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a one-map-at-a-time HTML explorer for map dumps.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("dumps", nargs="*", help="dump .json files (or folders holding exactly one dump)")
    ap.add_argument("--runs", action="append", metavar="DIR",
                    help="sheet work folder (summary.json + runs/<label>/); repeatable")
    ap.add_argument("--out", default=None, help="output folder (default <first --runs>/explorer)")
    ap.add_argument("--grep", default=DEFAULT_GREP, metavar="REGEX",
                    help="log lines shown in the caption (default %(default)r; '' = none)")
    ap.add_argument("--embed", action="store_true", help="inline the PNGs as base64 (one-file handoff; large)")
    ap.add_argument("--force", action="store_true", help="re-render PNGs even when they are newer than their dump")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--title", default=None)
    a = ap.parse_args(argv)
    if not a.runs and not a.dumps:
        ap.error("give --runs DIR and/or dump paths")
    if a.grep:
        try:
            re.compile(a.grep)
        except re.error as e:
            ap.error(f"--grep: {e}")
    build(a.runs, a.dumps, a.out, a.grep, a.embed, a.force, a.workers, a.title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
