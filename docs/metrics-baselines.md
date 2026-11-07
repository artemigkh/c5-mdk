# Map metric baselines: what normal maps look like

These are measured ranges for the user's reference map scripts, generated headless through c5gen. Use them to
check whether a new map script falls far outside what players expect. The numbers are in
`docs/metrics-baselines.json`. To compare a dump against them:

```
python host/metrics.py out/<name>/<dump>.json                 # print all metrics for one map
python host/metrics.py compare <dump>.json [--archetype Continents] [--all]
```

`compare` flags each metric outside the pooled p5–p95 for the same world size. With `--archetype`, it also
flags metrics outside that script's own p5–p95. It ends with a short verdict. It is advisory only and always
exits 0.

## Methodology

* **Scripts (7 archetypes):** `vp:Communitu_79a`, `vp:Continental_Drift`, `Continents`, `SmallContinents`,
  `vp:Terra`, `Oval`, `Archipelago`.
  * The VP copies were used where they exist: VP ships its own Terra and Continental_Drift.
  * Continents, SmallContinents, Oval and Archipelago are the base-game `Assets\Maps` copies, run under VP's
    MapGenerator, AssignStartingPlots and other overrides.
* **Sizes:** standard and huge. **Seeds:** 1..50 for each script and size, so **700 runs, 0 failures**.
  * Wall time was 399 s with 10 workers.
  * Mean seconds per run (standard / huge): Archipelago 2.9/5.6, Communitu 7.1/15.2, Continental_Drift 4.0/8.6,
    Continents 2.7/5.7, Oval 2.4/4.9, SmallContinents 2.8/5.9, Terra 3.7/7.4.
  * The slowest single run was Communitu huge at 34 s, measured under load.
* **Options:**
  * Every map-script option is left at its default.
  * Civ and city-state counts are the `Worlds` defaults: 8 civs and 16 CS at standard, 12 civs and 24 CS at huge.
  * Civs are drawn at random from the harness seed.
  * Other settings: era ancient, handicap Prince, `--areas literal`, runtime lua51.
* **Command:**
  * `python host/benchmark.py --seeds 50 --workers 10` runs c5gen with `--no-render --quiet` for each run.
  * Per-run metrics go to `out/bench/runs.jsonl`. The dumps are kept in `out/bench/dumps/`, about 200 MB,
    gitignored.
  * `--recompute` recalculates the metrics from the kept dumps after `host/metrics.py` changes.
  * `--report` prints the tables below.
* **Statistics:**
  * Each script × size cell stores n, mean, median, p5, p10, p90, p95, min and max. Percentiles use linear
    interpolation.
  * **Pooled** means all 7 archetypes together (350 runs per size), each weighted equally. A value inside the
    pooled p5–p95 is something one of the community's standard scripts produces.
  * Values are rounded to 3 significant digits.
* **Map dimensions are not uniform.** Several scripts override `GetMapInitData`:

  | Script | Standard | Huge |
  |---|---|---|
  | Default `Worlds` size | 80×52 | 128×80 |
  | Communitu | 79×53 | 97×66 (smaller than default huge) |
  | Continental_Drift | 88×58 | 140×88 |
  | Terra | 104×64 | 152×96 |
  | Oval | 64×40 | 104×64 |

  This is why "land per civ" and the absolute counts vary so much between scripts.

### Metric definitions (see `host/metrics.py`)

* **Grid and distance:**
  * The grid is odd-r with y=0 in the south.
  * Distances are true hex distances, taking the minimum over the X-wrapped copies. This matches the engine's
    `plotDistance` except at its seam quirk. Neighbour BFS cross-checks it in `tests/test_metrics.py`.
* **Land:**
  * *Land* means `plot_type != OCEAN`, so mountains count as land.
  * *Sea* means water that is not a lake. Lakes use the dump's `lake` flag.
  * *Lake count* is the number of connected lake bodies.
* **Coastal:** a land plot next to sea water. Ice still counts, and lakes do not.
* **On a river:**
  * At least one of the plot's 6 edges carries a river flag and the plot across that edge is land. This is
    the engine `IsRiver` rule.
  * *River edges* counts every river flag in the dump.
* **Fresh water:** on a river, next to a lake, or next to (or on) an oasis, Fountain of Youth or Lake Victoria.
  This approximates `Plot:IsFreshWater()`.
* **Resource classes:**
  * They come from the dump's `resource_class`.
  * Strategic means RUSH or MODERN, excluding artifacts. Luxury is LUXURY and bonus is BONUS.
  * Sea resources (fish, whales, pearls, crabs, coral) are counted too. "Per 100 land" is just a
    normalisation.
  * Strategic *quantity* is the sum of `resource_qty`.
* **Capitals and city-states:** the dump's `start_plots`, with majors and minors kept apart.
  * "Within 3" covers 37 plots, including the centre.
  * Landmasses are 6-connected land components, the same as the engine's landmass.
  * "Isolated" means the only capital on its landmass.
* **Polar rows:** the two outermost rows at each end (4 rows in total). Latitude is the row distance from the
  middle row, 0 at the equator and 1 at the edge.

## Results by size: median [p10–p90] per script

### standard

Map dimensions: Archipelago 80x52, Communitu_79a 79x53, Continental_Drift 88x58, Continents 80x52, Oval 64x40, SmallContinents 80x52, Terra 104x64.

| metric | Archipelago | Communitu_79a | Continental_Drift | Continents | Oval | SmallContinents | Terra | **pooled** |
|---|---|---|---|---|---|---|---|---|
| Land % of all plots | 19.6 [19.1–20.1] | 33.3 [30.5–35.5] | 23.7 [22.3–25.0] | 25.6 [24.9–26.0] | 42.0 [40.7–43.8] | 23.4 [23.0–23.9] | 25.1 [24.3–26.2] | **25.1 [19.8–41.3]** |
| Coast % of non-lake water | 51.7 [49.3–54.5] | 31.5 [25.2–37.4] | 25.3 [23.2–27.2] | 21.7 [18.7–26.2] | 27.0 [24.9–30.0] | 34.5 [31.8–37.1] | 28.0 [24.9–30.5] | **28.3 [22.3–50.3]** |
| Land tiles per major civ | 101.8 [99.4–104.3] | 174.2 [159.8–185.8] | 151.2 [142.2–159.3] | 132.9 [129.6–135.3] | 134.3 [130.2–140.1] | 121.9 [119.7–124.1] | 209.1 [202.1–217.9] | **136.1 [102.8–206.5]** |
| Largest landmass % of land | 15.8 [9.6–24.9] | 47.7 [36.2–59.4] | 39.3 [28.5–53.9] | 52.5 [37.1–67.8] | 99.4 [96.8–99.9] | 37.0 [23.9–62.7] | 56.0 [51.8–60.1] | **49.9 [17.9–98.5]** |
| Landmasses >= 30 tiles | 7.0 [4.9–9.0] | 4.0 [3.0–7.0] | 5.0 [3.9–7.0] | 3.0 [2.0–6.0] | 1.0 [1.0–2.0] | 6.0 [4.0–9.0] | 5.0 [3.0–7.0] | **5.0 [1.0–8.0]** |
| Islands of 1-5 tiles | 43.0 [36.0–51.0] | 24.0 [12.8–37.1] | 21.5 [13.9–29.0] | 5.5 [2.0–9.0] | 2.0 [0.9–5.0] | 20.0 [14.0–29.0] | 52.0 [41.9–61.0] | **22.0 [3.0–50.1]** |
| Grassland % of land | 31.0 [25.2–35.7] | 26.7 [22.2–29.6] | 38.2 [32.8–42.9] | 39.5 [31.5–45.3] | 41.3 [37.1–46.3] | 32.9 [27.8–40.8] | 36.7 [31.2–41.1] | **35.4 [26.5–43.2]** |
| Plains % of land | 28.7 [23.7–33.6] | 33.5 [27.4–37.3] | 31.3 [26.4–37.7] | 34.8 [29.4–39.5] | 30.4 [27.2–36.6] | 32.6 [26.6–37.2] | 31.7 [26.7–36.4] | **31.6 [26.7–37.3]** |
| Desert % of land | 10.6 [7.4–12.9] | 15.7 [10.6–21.6] | 10.8 [8.1–16.6] | 13.0 [8.9–19.0] | 13.6 [9.8–17.1] | 11.4 [7.0–14.6] | 12.0 [7.9–15.8] | **12.3 [8.0–17.8]** |
| Tundra % of land | 15.1 [12.3–19.4] | 19.1 [15.7–27.8] | 12.2 [7.3–17.7] | 9.2 [5.3–13.7] | 11.2 [9.6–12.9] | 15.6 [12.1–20.1] | 12.8 [10.5–15.9] | **13.2 [9.0–19.8]** |
| Snow % of land | 14.7 [11.4–18.2] | 3.8 [2.4–5.6] | 6.0 [3.0–11.3] | 2.7 [0.9–5.7] | 2.9 [1.9–3.7] | 7.2 [4.5–10.1] | 7.0 [5.2–9.5] | **5.4 [2.0–13.5]** |
| Hills % of land | 33.3 [30.1–36.6] | 33.5 [30.7–35.6] | 20.7 [17.3–23.5] | 23.8 [21.2–27.9] | 24.9 [23.1–27.4] | 30.5 [27.3–33.8] | 25.7 [23.5–28.4] | **27.3 [21.2–34.4]** |
| Mountains % of land | 1.7 [0.7–2.8] | 4.2 [3.2–4.9] | 2.1 [1.3–2.6] | 1.7 [1.0–2.8] | 3.0 [1.9–4.7] | 4.4 [2.8–6.8] | 2.6 [1.4–3.8] | **2.6 [1.2–4.8]** |
| Forest % of land | 16.3 [14.4–19.7] | 17.4 [14.6–21.3] | 28.5 [25.2–31.4] | 16.8 [14.4–18.9] | 20.6 [18.4–22.6] | 16.4 [14.4–19.5] | 21.1 [18.1–23.8] | **18.7 [15.1–27.6]** |
| Jungle % of land | 7.9 [5.4–10.6] | 7.6 [5.6–9.7] | 9.3 [5.9–12.0] | 9.8 [5.7–13.0] | 9.8 [8.4–10.6] | 8.4 [6.1–12.4] | 8.5 [6.7–10.4] | **8.7 [5.8–11.3]** |
| Marsh % of land | 1.2 [0.5–1.9] | 1.3 [0.8–1.8] | 5.2 [3.8–6.9] | 2.0 [1.1–2.8] | 2.5 [1.6–3.8] | 1.6 [0.7–2.2] | 1.8 [1.2–2.6] | **1.8 [0.9–4.4]** |
| Ice % of all water | 14.8 [14.2–15.3] | 19.9 [18.0–21.7] | 10.3 [9.9–10.8] | 17.1 [16.6–17.6] | 22.6 [21.6–23.4] | 16.4 [15.9–16.8] | 16.5 [16.0–16.7] | **16.6 [10.5–22.3]** |
| River edges per 100 land | 9.2 [7.4–10.7] | 21.5 [18.8–25.2] | 16.8 [14.0–19.6] | 16.8 [13.6–20.3] | 19.1 [14.7–22.7] | 13.7 [11.8–15.0] | 16.7 [12.9–19.3] | **16.4 [9.7–21.8]** |
| Land tiles on a river % | 12.1 [10.3–14.2] | 23.1 [20.4–26.0] | 18.7 [15.9–21.2] | 18.2 [15.4–21.4] | 20.1 [15.8–23.3] | 16.1 [14.0–17.3] | 18.0 [14.2–20.2] | **17.9 [12.9–22.9]** |
| Land tiles with fresh water % | 15.3 [12.8–17.4] | 31.2 [28.0–34.5] | 27.8 [23.4–30.6] | 23.8 [21.3–27.4] | 28.2 [25.8–32.7] | 20.2 [18.4–23.2] | 24.0 [20.6–27.0] | **24.8 [16.3–31.5]** |
| Lake tiles per 100 land | 0.4 [0.0–0.9] | 1.7 [1.0–2.5] | 1.8 [1.4–2.4] | 0.6 [0.3–1.4] | 1.8 [0.9–2.4] | 0.6 [0.3–1.2] | 1.2 [0.7–1.7] | **1.1 [0.3–2.2]** |
| Strategic resource tiles per 100 land | 13.6 [13.1–14.5] | 9.4 [8.9–10.2] | 11.7 [11.2–12.5] | 12.1 [11.6–12.9] | 11.7 [11.3–12.2] | 12.3 [11.6–13.1] | 11.3 [11.0–11.7] | **11.9 [9.6–13.3]** |
| Luxury resource tiles per 100 land | 14.2 [13.8–14.5] | 8.3 [7.7–8.8] | 9.3 [8.7–9.9] | 10.7 [10.4–11.0] | 10.7 [10.3–11.1] | 10.9 [10.2–11.5] | 7.2 [7.0–7.4] | **10.4 [7.3–14.0]** |
| Bonus resource tiles per 100 land | 34.4 [32.8–36.3] | 21.9 [19.9–24.3] | 20.3 [18.9–21.6] | 20.1 [18.2–21.9] | 16.8 [15.9–17.6] | 24.7 [23.4–26.6] | 20.1 [19.3–21.1] | **20.8 [17.1–33.7]** |
| Distinct luxury types on map | 18.0 [17.0–18.0] | 18.0 [18.0–18.0] | 18.0 [18.0–18.0] | 18.0 [17.9–18.0] | 18.0 [17.0–18.0] | 18.0 [18.0–18.0] | 20.0 [20.0–20.0] | **18.0 [18.0–20.0]** |
| Iron quantity per major civ | 8.5 [7.3–9.6] | 8.8 [7.8–10.0] | 11.2 [10.1–12.7] | 9.1 [8.1–10.5] | 9.4 [8.1–10.5] | 9.1 [8.0–10.3] | 15.1 [13.3–17.0] | **9.5 [8.0–14.5]** |
| Horse quantity per major civ | 4.2 [4.0–4.9] | 6.6 [5.5–7.8] | 5.8 [5.2–7.0] | 7.1 [6.1–7.7] | 6.4 [5.6–7.3] | 5.1 [4.2–5.8] | 8.9 [7.7–10.1] | **6.2 [4.4–8.6]** |
| Coal quantity per major civ | 4.9 [4.4–5.5] | 7.1 [5.7–8.4] | 7.5 [6.4–8.2] | 7.3 [6.0–8.4] | 7.4 [6.1–8.3] | 6.1 [5.2–7.0] | 10.1 [9.2–11.4] | **7.1 [5.0–9.8]** |
| Oil quantity per major civ | 10.5 [8.8–11.6] | 9.4 [7.2–11.7] | 13.2 [10.6–16.4] | 9.3 [7.8–11.0] | 9.2 [7.2–11.2] | 9.5 [8.1–11.6] | 15.8 [13.2–18.4] | **10.5 [8.0–15.1]** |
| Aluminum quantity per major civ | 11.2 [9.9–13.3] | 13.9 [12.2–16.6] | 13.1 [11.3–15.5] | 14.3 [11.9–16.0] | 13.3 [11.4–14.9] | 13.6 [11.3–16.3] | 19.4 [16.9–22.0] | **13.6 [10.9–18.5]** |
| Uranium quantity per major civ | 3.8 [3.4–4.1] | 4.2 [3.8–4.6] | 4.2 [3.8–4.9] | 3.8 [3.4–4.2] | 3.6 [3.4–4.0] | 3.9 [3.4–4.4] | 5.1 [4.8–5.8] | **4.0 [3.5–5.0]** |
| Natural wonders (distinct) | 5.0 [5.0–5.0] | 8.0 [8.0–8.0] | 5.0 [5.0–5.0] | 5.0 [5.0–5.0] | 5.0 [5.0–5.0] | 5.0 [5.0–5.0] | 5.0 [5.0–5.0] | **5.0 [5.0–8.0]** |
| Capital nearest-capital distance, mean | 13.9 [11.5–15.9] | 11.4 [9.9–13.5] | 11.0 [9.6–12.8] | 11.5 [10.2–14.3] | 11.2 [10.2–12.2] | 10.7 [9.2–12.8] | 10.2 [9.6–11.4] | **11.2 [9.9–13.9]** |
| Capital nearest-capital distance, min | 10.0 [9.0–12.1] | 9.0 [9.0–10.0] | 9.0 [9.0–10.0] | 9.0 [9.0–10.0] | 9.0 [9.0–10.1] | 9.0 [7.0–11.0] | 9.0 [9.0–10.0] | **9.0 [9.0–11.0]** |
| Capital to nearest city-state, min | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | **7.0 [7.0–7.0]** |
| Capitals coastal % | 100.0 [100.0–100.0] | 37.5 [12.5–51.3] | 50.0 [37.5–75.0] | 50.0 [25.0–75.0] | 50.0 [25.0–63.8] | 100.0 [100.0–100.0] | 43.8 [25.0–62.5] | **50.0 [25.0–100.0]** |
| Capitals on a river % | 25.0 [12.5–37.5] | 62.5 [50.0–87.5] | 37.5 [25.0–62.5] | 50.0 [25.0–62.5] | 50.0 [25.0–62.5] | 12.5 [0.0–25.0] | 50.0 [25.0–62.5] | **37.5 [12.5–63.8]** |
| Capitals with fresh water % | 25.0 [12.5–38.8] | 75.0 [62.5–87.5] | 62.5 [37.5–75.0] | 62.5 [36.2–75.0] | 62.5 [37.5–87.5] | 25.0 [0.0–37.5] | 62.5 [36.2–75.0] | **50.0 [12.5–75.0]** |
| Capitals on hills % | 25.0 [12.5–50.0] | 25.0 [11.3–50.0] | 25.0 [0.0–50.0] | 25.0 [0.0–37.5] | 25.0 [0.0–37.5] | 25.0 [12.5–50.0] | 25.0 [0.0–37.5] | **25.0 [0.0–50.0]** |
| Land tiles within 3 of capital, mean (of 37) | 20.4 [18.6–22.1] | 32.8 [30.4–34.5] | 29.9 [27.7–32.0] | 31.2 [29.0–33.4] | 31.4 [29.0–33.9] | 24.8 [23.5–25.9] | 31.6 [29.4–33.6] | **30.2 [21.2–33.4]** |
| Luxury tiles within 3 of capital, mean | 3.0 [3.0–3.0] | 3.0 [3.0–3.0] | 3.0 [3.0–3.0] | 3.0 [3.0–3.0] | 3.0 [3.0–3.0] | 3.0 [3.0–3.0] | 3.0 [3.0–3.0] | **3.0 [3.0–3.0]** |
| Major civs on the largest landmass | 2.0 [1.0–3.0] | 5.0 [4.0–6.0] | 4.0 [3.0–6.0] | 4.5 [3.0–6.0] | 8.0 [8.0–8.0] | 4.0 [2.0–8.0] | 8.0 [8.0–8.0] | **5.0 [2.0–8.0]** |
| Landmasses holding at least one capital | 7.0 [5.9–8.0] | 2.0 [2.0–3.0] | 2.5 [2.0–3.0] | 2.0 [2.0–3.0] | 1.0 [1.0–1.0] | 3.0 [1.0–4.0] | 1.0 [1.0–1.0] | **2.0 [1.0–6.0]** |
| Capitals alone on their landmass | 6.0 [4.0–8.0] | 0.0 [0.0–0.0] | 0.0 [0.0–0.0] | 0.0 [0.0–0.0] | 0.0 [0.0–0.0] | 0.0 [0.0–0.0] | 0.0 [0.0–0.0] | **0.0 [0.0–5.0]** |
| City-state nearest-CS distance, min | 5.0 [5.0–6.0] | 5.0 [5.0–6.0] | 5.0 [5.0–6.0] | 5.0 [5.0–6.0] | 5.0 [5.0–5.0] | 5.0 [5.0–6.1] | 5.0 [5.0–6.0] | **5.0 [5.0–6.0]** |
| City-state to nearest capital, min | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | **7.0 [7.0–7.0]** |
| City-states coastal % | 100.0 [93.8–100.0] | 87.5 [68.8–93.8] | 100.0 [93.8–100.0] | 93.8 [87.5–100.0] | 75.0 [62.5–87.5] | 93.8 [87.5–100.0] | 93.8 [81.2–100.0] | **93.8 [75.0–100.0]** |
| Land % in the 2 outermost rows (N+S) | 2.0 [0.9–6.2] | 0.0 [0.0–0.0] | 0.3 [0.0–2.3] | 0.0 [0.0–0.3] | 0.0 [0.0–0.0] | 0.6 [0.3–1.6] | 0.0 [0.0–0.0] | **0.0 [0.0–1.9]** |
| Mean latitude of tundra+snow (0 equator..1 pole) | 0.77 [0.76–0.78] | 0.79 [0.76–0.82] | 0.73 [0.69–0.76] | 0.70 [0.67–0.73] | 0.70 [0.69–0.71] | 0.73 [0.71–0.74] | 0.74 [0.73–0.76] | **0.73 [0.70–0.78]** |
| Mean latitude of desert | 0.36 [0.32–0.39] | 0.39 [0.34–0.44] | 0.35 [0.33–0.38] | 0.36 [0.33–0.39] | 0.34 [0.32–0.37] | 0.35 [0.31–0.38] | 0.36 [0.34–0.39] | **0.36 [0.32–0.40]** |
| Desert tiles with flood plains % | 7.6 [1.6–15.1] | 17.6 [13.0–23.7] | 15.4 [9.3–22.3] | 16.2 [10.2–23.7] | 15.9 [8.2–20.8] | 10.6 [6.0–17.4] | 14.5 [8.4–20.9] | **14.6 [6.2–21.4]** |

### huge

Map dimensions: Archipelago 128x80, Communitu_79a 97x66, Continental_Drift 140x88, Continents 128x80, Oval 104x64, SmallContinents 128x80, Terra 152x96.

| metric | Archipelago | Communitu_79a | Continental_Drift | Continents | Oval | SmallContinents | Terra | **pooled** |
|---|---|---|---|---|---|---|---|---|
| Land % of all plots | 20.3 [19.9–20.6] | 34.5 [32.9–36.7] | 23.6 [23.0–24.8] | 26.0 [25.5–26.3] | 42.0 [40.6–43.9] | 23.7 [23.3–24.0] | 24.3 [23.7–25.5] | **24.7 [20.4–41.1]** |
| Coast % of non-lake water | 42.9 [41.1–44.6] | 30.9 [25.7–35.6] | 25.1 [23.4–26.6] | 17.2 [14.6–19.3] | 18.8 [17.6–20.6] | 28.2 [26.0–30.0] | 20.7 [18.1–23.0] | **25.0 [17.4–42.3]** |
| Land tiles per major civ | 172.8 [170.2–176.2] | 184.0 [175.5–195.5] | 242.8 [236.3–254.4] | 221.5 [217.5–224.6] | 232.8 [225.1–243.3] | 202.2 [198.9–204.9] | 296.0 [287.6–310.3] | **221.5 [173.7–290.9]** |
| Largest landmass % of land | 12.6 [9.9–20.3] | 46.5 [34.6–61.1] | 35.9 [23.7–52.3] | 51.7 [41.6–64.2] | 99.6 [97.5–99.9] | 30.6 [21.4–53.0] | 58.4 [51.2–61.4] | **46.6 [15.7–99.0]** |
| Landmasses >= 30 tiles | 18.0 [15.0–22.0] | 5.0 [3.0–8.0] | 10.0 [7.0–13.1] | 4.0 [3.0–6.0] | 1.0 [1.0–2.0] | 9.5 [7.9–12.0] | 6.0 [4.0–8.0] | **7.0 [1.0–17.0]** |
| Islands of 1-5 tiles | 78.0 [65.7–90.1] | 41.5 [28.9–54.2] | 46.5 [38.9–58.0] | 15.0 [11.0–23.0] | 3.0 [1.0–7.0] | 55.0 [44.0–62.2] | 87.5 [68.0–110.2] | **48.5 [4.0–86.1]** |
| Grassland % of land | 31.6 [25.5–34.6] | 25.3 [22.4–29.0] | 31.2 [27.4–38.2] | 38.3 [32.6–47.1] | 40.3 [33.3–45.2] | 34.5 [29.7–40.1] | 33.4 [25.9–42.1] | **33.4 [25.3–42.6]** |
| Plains % of land | 28.4 [24.1–32.5] | 32.3 [28.7–36.9] | 31.5 [26.2–34.7] | 36.2 [30.3–41.3] | 34.4 [30.3–40.9] | 30.9 [27.6–37.1] | 35.1 [27.7–42.1] | **32.6 [27.1–39.1]** |
| Desert % of land | 10.1 [7.8–13.1] | 16.6 [11.9–20.8] | 11.9 [7.3–14.4] | 13.3 [9.1–18.5] | 12.7 [9.7–14.9] | 10.9 [7.9–14.7] | 11.6 [7.3–15.0] | **12.2 [8.1–17.7]** |
| Tundra % of land | 15.7 [12.5–19.5] | 21.6 [16.4–29.0] | 16.9 [12.8–20.9] | 9.0 [6.4–12.6] | 10.2 [8.3–11.8] | 15.3 [11.5–19.1] | 12.4 [10.4–15.5] | **14.0 [8.7–21.3]** |
| Snow % of land | 13.7 [10.8–18.2] | 4.0 [1.9–5.5] | 8.4 [5.4–12.9] | 1.9 [0.5–4.4] | 2.3 [1.4–3.4] | 6.8 [5.2–10.0] | 6.9 [4.6–9.3] | **5.7 [1.6–13.2]** |
| Hills % of land | 31.3 [28.9–33.5] | 33.5 [32.3–35.1] | 20.1 [17.3–23.1] | 23.8 [21.8–26.9] | 24.8 [23.0–25.8] | 29.0 [26.5–30.8] | 24.2 [21.7–26.6] | **25.8 [21.0–33.4]** |
| Mountains % of land | 2.8 [2.2–3.6] | 4.2 [3.3–4.7] | 1.8 [1.4–2.3] | 2.4 [1.6–3.8] | 2.9 [2.3–3.8] | 6.1 [4.5–7.8] | 1.7 [1.0–2.6] | **2.8 [1.5–5.6]** |
| Forest % of land | 19.1 [16.8–21.3] | 17.9 [14.9–20.1] | 28.9 [27.6–31.9] | 20.8 [18.1–23.4] | 20.6 [18.9–22.6] | 20.4 [18.3–23.0] | 16.4 [14.2–19.1] | **19.9 [16.1–28.2]** |
| Jungle % of land | 8.6 [6.0–10.8] | 7.7 [6.1–9.3] | 8.0 [5.2–9.4] | 10.9 [8.2–14.4] | 12.6 [11.1–14.1] | 9.6 [6.0–12.6] | 11.0 [9.0–12.7] | **9.4 [6.2–13.0]** |
| Marsh % of land | 1.6 [0.8–2.3] | 1.3 [0.9–1.7] | 4.6 [3.1–6.4] | 2.0 [1.3–2.8] | 2.1 [1.4–2.7] | 1.6 [1.1–2.2] | 1.7 [1.1–2.6] | **1.8 [1.1–3.8]** |
| Ice % of all water | 14.6 [14.0–14.9] | 18.1 [16.7–19.8] | 6.9 [6.7–7.0] | 17.0 [16.7–17.5] | 21.9 [21.3–22.7] | 16.2 [15.9–16.6] | 16.1 [15.8–16.4] | **16.3 [7.0–21.6]** |
| River edges per 100 land | 11.4 [10.2–12.5] | 23.8 [21.0–26.6] | 17.9 [16.2–20.0] | 20.7 [17.1–24.5] | 24.6 [21.5–26.8] | 15.4 [13.5–17.8] | 20.1 [18.3–23.0] | **19.5 [12.0–25.1]** |
| Land tiles on a river % | 14.3 [12.8–15.7] | 24.6 [22.1–26.9] | 19.5 [17.9–21.8] | 21.5 [18.4–25.1] | 24.9 [22.1–26.9] | 17.1 [15.2–19.3] | 21.1 [19.2–23.3] | **20.7 [14.6–25.5]** |
| Land tiles with fresh water % | 18.6 [17.2–20.1] | 32.7 [29.5–34.7] | 27.9 [25.8–30.1] | 27.3 [24.8–30.3] | 30.8 [27.8–32.6] | 22.1 [20.1–24.1] | 26.4 [24.7–28.6] | **27.2 [19.2–32.6]** |
| Lake tiles per 100 land | 0.7 [0.4–1.1] | 1.8 [1.0–2.6] | 1.8 [1.5–2.2] | 0.8 [0.6–1.4] | 0.9 [0.5–1.3] | 0.9 [0.5–1.4] | 0.9 [0.5–1.3] | **1.0 [0.5–1.9]** |
| Strategic resource tiles per 100 land | 11.4 [11.0–12.0] | 8.9 [8.6–9.3] | 11.0 [10.5–11.4] | 10.4 [10.1–10.8] | 10.2 [9.9–10.4] | 10.5 [10.0–10.8] | 10.8 [10.4–11.2] | **10.6 [9.1–11.4]** |
| Luxury resource tiles per 100 land | 9.7 [9.4–9.8] | 8.9 [8.5–9.2] | 6.8 [6.4–7.1] | 7.5 [7.4–7.7] | 7.2 [6.9–7.4] | 8.1 [7.9–8.3] | 5.7 [5.5–5.9] | **7.5 [5.8–9.6]** |
| Bonus resource tiles per 100 land | 27.8 [27.1–28.8] | 20.9 [19.4–22.9] | 19.0 [18.2–19.7] | 16.4 [15.5–17.5] | 13.9 [13.4–14.5] | 20.4 [19.5–21.4] | 17.4 [16.7–18.4] | **18.9 [14.2–27.5]** |
| Distinct luxury types on map | 26.0 [26.0–26.0] | 26.0 [26.0–26.0] | 26.0 [25.9–26.0] | 26.0 [26.0–26.0] | 26.0 [26.0–26.0] | 26.0 [26.0–26.0] | 27.0 [27.0–27.0] | **26.0 [26.0–27.0]** |
| Iron quantity per major civ | 13.3 [12.1–14.9] | 9.2 [8.2–10.0] | 18.0 [16.5–19.8] | 13.5 [12.6–15.3] | 14.2 [12.7–15.3] | 13.8 [12.0–14.9] | 19.3 [17.9–21.4] | **14.1 [9.5–19.3]** |
| Horse quantity per major civ | 6.0 [5.2–6.8] | 7.1 [6.2–7.6] | 8.5 [7.4–9.8] | 10.3 [9.2–11.6] | 10.5 [9.2–11.7] | 7.6 [6.6–8.3] | 13.4 [11.9–15.3] | **8.5 [6.1–12.8]** |
| Coal quantity per major civ | 7.0 [5.8–8.1] | 6.9 [6.0–7.8] | 10.0 [8.6–11.4] | 10.8 [9.6–12.1] | 10.8 [9.8–12.1] | 8.8 [7.9–9.7] | 12.6 [10.9–14.5] | **9.7 [6.7–12.3]** |
| Oil quantity per major civ | 15.3 [12.9–17.8] | 9.6 [8.2–11.1] | 20.3 [16.9–23.8] | 12.9 [10.7–14.8] | 13.0 [11.5–14.4] | 13.5 [12.2–15.4] | 21.3 [18.5–24.6] | **14.2 [9.9–22.1]** |
| Aluminum quantity per major civ | 16.6 [14.6–18.7] | 14.6 [12.7–16.4] | 20.7 [18.2–23.4] | 19.7 [16.2–22.8] | 19.7 [17.8–22.5] | 18.6 [15.7–20.9] | 28.8 [23.8–32.2] | **19.1 [14.6–26.6]** |
| Uranium quantity per major civ | 4.3 [3.7–4.8] | 3.6 [3.2–4.1] | 5.8 [5.2–6.4] | 4.7 [4.2–5.2] | 4.9 [4.7–5.3] | 4.5 [4.1–4.9] | 6.6 [5.9–7.1] | **4.8 [3.7–6.4]** |
| Natural wonders (distinct) | 7.0 [7.0–7.0] | 12.0 [12.0–12.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | **7.0 [7.0–12.0]** |
| Capital nearest-capital distance, mean | 16.5 [14.5–18.8] | 11.1 [10.1–12.8] | 12.6 [10.7–15.9] | 13.6 [12.1–15.5] | 13.8 [12.7–14.9] | 13.4 [11.7–15.1] | 11.9 [10.6–13.2] | **13.2 [10.9–16.3]** |
| Capital nearest-capital distance, min | 10.0 [9.0–12.0] | 9.0 [8.0–9.0] | 9.0 [9.0–11.0] | 10.0 [9.0–11.1] | 10.0 [9.0–11.0] | 9.0 [9.0–11.0] | 9.0 [9.0–10.0] | **9.0 [9.0–11.0]** |
| Capital to nearest city-state, min | 7.0 [7.0–8.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | **7.0 [7.0–7.0]** |
| Capitals coastal % | 100.0 [100.0–100.0] | 33.3 [16.7–50.0] | 41.7 [25.0–58.3] | 33.3 [16.7–50.0] | 25.0 [16.7–50.0] | 100.0 [100.0–100.0] | 33.3 [16.7–50.0] | **41.7 [16.7–100.0]** |
| Capitals on a river % | 16.7 [8.3–41.7] | 66.7 [50.0–83.3] | 50.0 [32.5–66.7] | 66.7 [50.0–83.3] | 66.7 [50.0–83.3] | 16.7 [7.5–33.3] | 58.3 [41.7–75.0] | **54.2 [16.7–75.0]** |
| Capitals with fresh water % | 25.0 [16.7–42.5] | 75.0 [66.7–91.7] | 66.7 [50.0–84.2] | 75.0 [58.3–84.2] | 75.0 [58.3–91.7] | 25.0 [8.3–41.7] | 66.7 [49.2–83.3] | **66.7 [16.7–83.3]** |
| Capitals on hills % | 25.0 [8.3–42.5] | 25.0 [8.3–41.7] | 25.0 [8.3–41.7] | 16.7 [0.0–33.3] | 16.7 [7.5–33.3] | 25.0 [15.8–41.7] | 25.0 [7.5–41.7] | **25.0 [8.3–41.7]** |
| Land tiles within 3 of capital, mean (of 37) | 24.1 [22.4–25.6] | 33.1 [31.2–34.6] | 31.1 [29.1–32.8] | 33.7 [31.6–35.0] | 33.8 [31.6–35.0] | 26.2 [25.2–27.2] | 33.2 [31.7–34.8] | **32.1 [24.7–34.4]** |
| Luxury tiles within 3 of capital, mean | 3.0 [2.9–3.0] | 3.0 [3.0–3.0] | 3.0 [3.0–3.0] | 3.0 [3.0–3.0] | 3.0 [3.0–3.0] | 3.0 [3.0–3.0] | 3.0 [3.0–3.0] | **3.0 [3.0–3.0]** |
| Major civs on the largest landmass | 2.0 [1.0–4.0] | 7.5 [5.0–10.0] | 7.0 [3.9–10.0] | 7.0 [4.9–9.0] | 12.0 [12.0–12.0] | 5.0 [3.0–10.0] | 12.0 [12.0–12.0] | **8.0 [2.0–12.0]** |
| Landmasses holding at least one capital | 10.0 [7.0–11.0] | 2.0 [2.0–3.0] | 3.0 [2.0–5.0] | 2.0 [2.0–3.0] | 1.0 [1.0–1.0] | 4.0 [2.0–5.0] | 1.0 [1.0–1.0] | **2.0 [1.0–9.0]** |
| Capitals alone on their landmass | 8.0 [4.9–10.0] | 0.0 [0.0–0.0] | 0.0 [0.0–0.0] | 0.0 [0.0–0.0] | 0.0 [0.0–0.0] | 0.0 [0.0–0.0] | 0.0 [0.0–0.0] | **0.0 [0.0–6.0]** |
| City-state nearest-CS distance, min | 5.0 [5.0–5.0] | 5.0 [5.0–5.0] | 5.0 [5.0–6.0] | 5.0 [5.0–6.0] | 5.0 [5.0–5.0] | 5.0 [5.0–6.0] | 5.0 [5.0–6.0] | **5.0 [5.0–6.0]** |
| City-state to nearest capital, min | 7.0 [7.0–8.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | 7.0 [7.0–7.0] | **7.0 [7.0–7.0]** |
| City-states coastal % | 100.0 [95.8–100.0] | 79.2 [66.7–91.7] | 95.8 [91.7–100.0] | 100.0 [91.7–100.0] | 83.3 [79.2–91.7] | 100.0 [91.7–100.0] | 91.7 [87.5–100.0] | **95.8 [79.2–100.0]** |
| Land % in the 2 outermost rows (N+S) | 1.0 [0.4–2.8] | 0.0 [0.0–0.0] | 0.0 [0.0–0.5] | 0.0 [0.0–0.0] | 0.0 [0.0–0.0] | 0.6 [0.2–1.0] | 0.0 [0.0–0.0] | **0.0 [0.0–0.8]** |
| Mean latitude of tundra+snow (0 equator..1 pole) | 0.76 [0.75–0.78] | 0.81 [0.78–0.83] | 0.73 [0.71–0.75] | 0.68 [0.65–0.71] | 0.69 [0.68–0.70] | 0.72 [0.71–0.73] | 0.74 [0.71–0.75] | **0.73 [0.68–0.80]** |
| Mean latitude of desert | 0.35 [0.32–0.38] | 0.39 [0.35–0.43] | 0.36 [0.32–0.39] | 0.35 [0.33–0.39] | 0.34 [0.31–0.36] | 0.35 [0.32–0.38] | 0.36 [0.32–0.38] | **0.36 [0.32–0.40]** |
| Desert tiles with flood plains % | 9.9 [5.1–13.1] | 19.0 [15.1–23.5] | 15.6 [11.3–23.0] | 16.9 [11.8–24.0] | 19.5 [15.6–24.4] | 11.8 [7.8–16.7] | 18.8 [13.7–26.0] | **16.2 [9.6–23.4]** |

## Normal ranges for a new map script

Each range below is the **pooled p5–p95** at standard, with huge in parentheses where it differs. A value
outside it is unusual for the community's standard scripts. Check whether that is intended.

### Geography

| Metric | Normal range | What it means |
|---|---|---|
| Land % | 19–43 % (20–43 %), median 25 % | Archipelago is the low end (≈20 %) and Oval the high end (≈42 %). Most continent scripts sit at 23–26 %. Below 18 % or above 45 % is outside every reference script. |
| Coast % of sea | 21–53 % (17–43 %) | Continents and Terra have the most deep ocean. Archipelago is half coast. |
| Land tiles per civ | 100–210 (170–300) | Archipelago and Terra set the ends. Terra's New World is empty at the start. |
| Largest landmass % of land | 14–99.6 % | This is the archetype signature, so the range is not a quality check. Pangaea-like ≥ 95 %, two continents ≈ 50 % + 30 %, island maps ≤ 25 %. |
| Landmasses ≥ 30 tiles | 1–9 (1–20) | Archipelago gives about 7 (18). |
| 1–5 tile islands | 1–55 (2–98) | Oval and Continents have few, about 5. Terra and Archipelago have about 50 (80–90). |
| Coastal land % of land | 25–85 % (18–72 %) | Archipelago is 85 %. Pangaea and Oval are 25 %. |
| Lakes | 2–16 bodies (8–30), 0.2–2.4 lake tiles per 100 land | Lakes are small everywhere: 1–2 lake tiles per 100 land. |
| Ice % of all water | 10–23 % (7–22 %) | Polar ice rows are universal: 84–100 % of the polar-row water is ice. Polar land is ≈ 0 %. |

### Terrain and features

| Metric | Normal range | What it means |
|---|---|---|
| Terrain mix (% of land) | Grass 25–45 %, plains 25–39 %, desert 7–20 %, tundra 8–23 %, snow 1.7–15 % | Plains and desert are stable across all scripts. Snow is the most script-dependent. Archipelago's polar islets push it to about 15 %. |
| Hills % of land | 20–35 % | Continental_Drift is about 21 %. Communitu and Archipelago are about 33 %. VP maps are hillier than many people expect. |
| Mountains % of land | 1.0–5.4 % (1.3–6.5 %) | SmallContinents and Communitu are the high end. Above 7 % is outside every reference script. |
| Flat land % | 60–78 % | Stable. |
| Forest % of land | 14–30 % | Continental_Drift is about 28 %. Everything else is 16–21 %. |
| Jungle % of land | 5–12 % (6–14 %) | Stable. |
| Marsh % of land | 0.7–5.7 % | Continental_Drift is about 5 %. Everything else is 1–2.5 %. |
| Flood plains % of land | 0.4–3.8 % | 4–24 % of desert tiles carry flood plains. |
| Oases | 0–10 (2–19) | Communitu has the most. |
| Atolls | 1–30 (3–48) | Oval has about 2. Communitu has about 26 and Continental_Drift about 17 (39 and 43 at huge). Other scripts have 7–10. |
| Natural wonders | Exactly 5 at standard and 7 at huge | Communitu places its own count: 8 at standard and 12 at huge. |
| Mean latitude of tundra and snow | 0.69–0.80 | This is about 0.73 everywhere. A value below 0.6 means cold terrain is not polar. |
| Mean latitude of desert | 0.31–0.40 | About 0.36 everywhere: the subtropical band. |
| Mean latitude of jungle | 0.06–0.13 | Jungle is equatorial. |

### Rivers and fresh water

| Metric | Normal range | What it means |
|---|---|---|
| River edges per 100 land | 9–24 (11–26) | Archipelago is the low end and Communitu or Oval the high end. |
| Land tiles on a river | 12–25 % (14–26 %) | |
| Land tiles with fresh water | 15–33 % (18–34 %) | |

### Resources

| Metric | Normal range | What it means |
|---|---|---|
| Strategic tiles per 100 land | 9.3–13.8 (8.8–11.6) | This is the most stable resource density. Communitu is the low end. |
| Luxury tiles | 103–122 (191–204) | This is a near-constant count per world size, not a density, so luxury per 100 land runs 7–14 (5.6–9.7) and moves inversely with land. That works out to about 14 luxury tiles per civ at standard and 17 at huge. |
| Distinct luxury types | 18, with Terra at 20 (26, with Terra at 27) | The most common luxury holds 6.6–8.7 % (4.9–6 %) of luxury tiles. |
| Bonus tiles per 100 land | 17–35 (14–28) | Sea bonuses are included, so island maps run high. |
| Strategic quantity per civ (standard) | Iron 7.6–15.6, horse 4.1–9.3, coal 4.8–10.4, oil 7.8–16.8, aluminium 10–21, uranium 3.4–5.4 | Scales with land per civ. Terra is the high end. |
| Strategic quantity per civ (huge) | Iron 8.7–20, horse 5.6–14, coal 6.3–13, oil 9.4–23.5, aluminium 14–29, uranium 3.5–6.8 | Same pattern as standard. |

### Capitals and city-states

| Metric | Normal range | What it means |
|---|---|---|
| Nearest-capital distance, mean | 9.4–15 (10.5–17) | |
| Nearest-capital distance, min | 8–11 | 9 in almost every run, which matches VP ASP's spacing. A minimum below 7 is a red flag. It was seen once: Terra seed 1 at standard, with a distance of 5. |
| Capital to nearest CS, min | Exactly 7 | Always 7 in all 700 runs. |
| CS to nearest CS, min | 5–6 | |
| CS to nearest capital, mean | 8–19 (10–24) | Terra pushes CS onto the New World, about 18 (24). |
| Capitals coastal | 25–100 % (17–100 %) | Archipelago and SmallContinents are always 100 %. Continent maps put only 35–50 % of capitals on the coast (25–42 % at huge). |
| Capitals on a river | 12–75 % (8–83 %) | |
| Capitals with fresh water | 12–88 % (17–92 %) | Communitu is about 75 % fresh. Island maps are about 25 %. |
| Capitals on hills | 0–50 %, median 25 % | Stable across scripts. |
| Capitals next to a mountain | 0–25 % | |
| Capitals on tundra/snow | 0–25 % | |
| Capitals on desert | 0–25 % | |
| Land within 3 of capital, mean | 20–34 of 37 (23–35) | Island maps are about 20–25. The per-map minimum is 13–28. |
| Luxuries within 3 of capital | Exactly 3.0 | VP's capital luxury placement. Anything else means ASP's luxury pass did not run normally. |
| Strategics within 3 of capital | 2.3–4.6 | |
| Bonus resources within 3 of capital | 1.8–3.4 | |
| Capitals sharing the largest landmass | 1–8 of 8 (2–12 of 12) | Archetype signature. |
| Isolated capitals | 0, except Archipelago (4–8 at standard, 5–10 at huge) | |
| City-states coastal | 69–100 % | VP ASP strongly prefers coastal CS sites. Oval and Communitu are the low end, at about 75–80 %. |
| Bad starts (on water or mountain) | 0 | Always 0. |

### Metrics a new script should respect

These are stable across all seven archetypes: the gap between the script medians is small next to the
pooled range. A new script that misses them is wrong, not just different.

* **Placement constraints (ASP):** capital spacing has a minimum of about 9. The capital-to-CS minimum is 7,
  the CS-to-CS minimum is 5, and every capital gets 3 luxuries within radius 3. Start plots are never on
  water or mountains. If a script overrides ASP and breaks these, players will notice.
* **Resource economy:**
  * Strategic tiles run about 9–14 per 100 land.
  * The luxury tile count is fixed per world size, and the type count is 18 at standard and 26 at huge.
  * Natural wonders are 5 at standard and 7 at huge.
* **Climate bands:**
  * Mean latitudes: desert about 0.36, tundra and snow about 0.73, jungle about 0.07.
  * Polar rows are water and mostly ice.
  * Plains are 25–39 % of land, desert 7–20 % and jungle 5–13 %.
* **Relief:** hills 20–35 %, mountains 1–6 %, flat land 60–78 %.
* **Fresh water:** 15–33 % of land and 12–25 % on rivers. Rivers are never absent.

### Metrics that legitimately differ by archetype

Do not treat these as errors. Compare them with `--archetype`.

* Land %, largest and second landmass share, number of landmasses, and tiny islands.
* Coast and ocean share of the sea, and coastal land %.
* Capitals sharing a landmass, landmasses that hold capitals, isolated capitals, and coastal capitals.
* Land per civ, and through it the absolute strategic quantities.
* Snow % (Archipelago), marsh and forest (Continental_Drift), atolls, oases and lakes.

## Archetype characterizations (standard size unless noted)

* **Archipelago:**
  * Land is 20 %. The sea is half coast.
  * There are about 7 landmasses of ≥ 30 tiles (18 at huge). The largest is only 16 % of land, and there are
    about 43 one-to-five-tile islets.
  * Every capital is coastal. 6 of 8 sit alone on their own island, and capitals have only about 20 land tiles
    within radius 3.
  * It has the fewest rivers (9 edges per 100 land) and fresh water on only 15 % of land, so only 25 % of
    capitals have fresh water.
  * It has the most snow (15 % of land, from polar islets) and the most land in the polar rows (2 %).
  * Its bonus density is the highest (34 per 100, from fish), and its luxury density is the highest (14 per
    100) because the fixed luxury count sits on little land.
  * Capitals are the farthest apart (mean nearest-capital distance 14).
* **Communitu_79a:**
  * It uses its own dimensions, and its huge map is smaller than the default.
  * Land is 33 %, it is the hilliest map (34 % hills, 4 % mountains), and it has the most tundra (19 %) and
    desert (16 %).
  * It is the river-richest script: 21.5 edges per 100 land, 31 % fresh water, and 62 % of capitals on a river
    (75 % fresh).
  * Only about 37 % of capitals are coastal.
  * It places extra natural wonders (8, or 12 at huge), and has the most atolls (≈ 26) and oases (≈ 8).
  * It has the lowest strategic density (9.4 per 100).
  * Communitu forces full polar ice: 100 % of the polar rows are ice.
  * Jungle sits a little farther from the equator than in other scripts (mean latitude 0.12).
* **Continental_Drift (VP):**
  * Land is 24 %, and the largest landmass holds about 39 % of land.
  * It is the forest-and-wetland map: 28 % forest and 5 % marsh, both highest.
  * It has the fewest hills (21 %) and the most lakes: ≈ 11 bodies, tied with Communitu and Terra, and 27 at
    huge.
  * It has the least ice: 10 % of water, or 7 % at huge.
  * It has many small islands (≈ 21 at standard, 46 at huge).
* **Continents:**
  * Two big continents: the largest is ≈ 52 % of land and the second ≈ 32 %, with few islets (≈ 5).
  * Capitals split roughly 4/4.
  * It has the most deep ocean (78 % of the sea) and the least cold terrain (tundra 9 %, snow 2.7 %).
* **Oval:**
  * A single landmass holds 99.4 % of the land, on a smaller grid (64×40, or 104×64 at huge). Land is 42 %,
    the highest, and every civ shares the continent.
  * The coastline is short: only 27 % of land is coastal, and just 75 % of city-states are coastal, the
    lowest.
  * City-states are packed (mean CS-to-CS distance 6.8). Bonus density is the lowest (17 per 100).
  * It has the highest ice share of water (23 %), because of the small sea and the polar rows.
* **SmallContinents:**
  * About 6 landmasses of ≥ 30 tiles. The largest is about 37 % of land, but it varies widely (24–63 %).
  * Every capital is coastal, but only 12 % sit on a river and 25 % have fresh water.
  * It has the most mountains (4.4 %, or 6 % at huge).
  * Capitals have about 25 land tiles within radius 3.
  * Capital spacing hits the floor more often than elsewhere: 8 of 50 standard seeds had a minimum of 7.
* **Terra (VP):**
  * It uses the largest grid (104×64 at standard).
  * All 8 civs (12 at huge) start on the Old World, which is about 56 % of land. The rest of the land is an
    empty New World plus about 52 islets.
  * Land per civ is the highest (209, or 296 at huge), so strategic quantity per civ is the highest (iron
    15, oil 16) and luxury density is the lowest (7.2 per 100).
  * City-states sit far from capitals (mean CS-to-capital distance 18) because many are on the New World.
  * It is the only script with more than 18 luxury types (20 at standard, 27 at huge).

## Failures and outliers

* **No failures.** All 700 runs completed, and no start was placed on water or a mountain.
* **Capital spacing below 8.** These are legal under ASP fallbacks but unusual:
  * Terra seed 1 at standard: Ottoman and Poland are 5 apart on the Old World.
  * SmallContinents seed 30 at huge: 6 apart.
  * There are scattered 7s in SmallContinents (8 of 50 standard seeds), Communitu (1 standard, 4 huge) and
    one each in Continents and Continental_Drift.
* **Archipelago capitals with very little land.** Some capitals have only 6–11 land tiles within radius 3
  (11 of 50 standard seeds), for example seed 42 with 6 and seed 48 with 7.
* **Size scaling is not uniform:**
  * Huge has 2.46× the plots of standard but only 1.5× the civs. Land per civ grows about 1.6×.
  * The luxury count grows only about 1.75×, so luxury density per land drops from about 10.4 to about 7.5.
  * Communitu's huge map (97×66) is only 1.5× its standard map.
