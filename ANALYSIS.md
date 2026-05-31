# E07 Fullscan — Analysis Notes

Chronological development diary — results, discussions, decisions, and dead ends.
Technical API reference: README.md.

**Started:** 2026-05-08

---

## Reference

### Scan Geometry

| Item | Value |
|---|---|
| Plate | MOD108 / PL12 / tohoku-v1 / AREA00 |
| Views | 2025 (45 × 45 grid) |
| FOV spacing | ~0.5 mm |
| FOV size | ~594 × 594 μm |
| **Pixel scale** | **0.29 μm/px** (scanner JSON says 3.0 — wrong) |
| Emulsion depth | ~150 μm |
| Slices | ~100, z-spacing ~1.5 μm/slice |

Confirmed 0.29 μm/px from scan geometry: 2048 px × 0.29 = 594 μm ≈ 0.5 mm FOV spacing.

### Pipeline

```
SPNG images
    │  [per slice per view]
    ▼  Z-projection → fog removal → Otsu threshold → noise removal
    │  HoughLinesP
    ▼  Track segments  (chunk_NNNN.parquet, ~24M tracks total)
    │  quality metrics: length_px, mean_intens, angle_deg, n_grains, grain_density
    ▼  pairwise intersection + endpoint check
    │  Per-slice vertex candidates  (vertices.parquet)
    ▼  XY proximity merge across z-slices
    Merged vertex candidates  (vertices_merged.parquet)
```

![Processing pipeline](docs/pipeline.png)

### Physics Goals

**Current phase**: efficiency-first selection of *any* reaction vertex.
Targets: beam interactions, single-Λ hypernuclei, α decay chains, nuclear stars.

**Ultimate goal**: double hypernuclei (ΛΛ) search.
Signature: two connected vertices separated by ~100–500 μm (30–167 px):
1. **Primary vertex** — beam + target → ΛΛ-hypernucleus + other particles
2. **Secondary vertex** — hypernucleus weak decay (kink or small star)

### Beam Direction

Beam travels in the emulsion plane along X (horizontal in image).
22% of all tracks have `angle_deg < 15°` or `> 165°` (beam direction).
`beam_angle_cut = 15°` removes these.

---

## Development Log

---

## 2026-05-08 — First track analysis run; pixel scale correction

**What was done:**
- Ran full `e07analyze` on 2025 views → `results/merged.parquet` (~24M tracks).
- Discovered pixel scale error in scanner JSON: metadata says 3.0 μm/px but scan geometry
  gives **0.29 μm/px**. Corrected `px_scale_um` in `config/default.yaml`.
- Consequence: `grain_density` in existing parquet is 10× too low (computed with 3.0).
  Use `n_grains` directly until track analysis is re-run with 0.29.

**Track quality metrics confirmed:**
- `mean_intens` is independent of px_scale → reliable for quality cuts.
- `grain_density` = n_grains / (length_px × px_scale) × 100 grains/100 μm;
  corrected values will be meaningful for particle ID.
- `width_px`: transverse spread of grain centroids; heavier/slower tracks are wider.

**Hough parameter tuning (visual check):**

| Parameter | Old | New | Reason |
|---|---|---|---|
| `hough_thr` | 20 | 35 | Reduce noise track count |
| `hough_ml` | 25 px | 50 px | 25 px = 7.3 μm; too many noise segments |
| `hough_mg` | 4 | 5 | Marginal improvement |
| `grain_radius` | 10 px | 15 px | Better grain association at 0.29 μm/px |

**v1 vertex run (first attempt):**
- Parameters: `min_len=100, min_intens=12, max_ep=100`, no beam cut
- Result: **95,160 raw → 8,468 merged**
- Observation: very conservative; missed α tracks (~86 px < 100 px cutoff).

---

## 2026-05-09 — Vertex finding v2; parameter relaxation

**What was done:**
- Relaxed vertex finding parameters for efficiency-first approach:
  - `min_len_px`: 100 → **50 px** (catches α tracks at ~86 px)
  - `min_intens`: 12 → **10.0**
  - `max_ep`: 100 → **150 px**
  - `beam_angle_cut`: 0 → **15°** (remove beam-parallel tracks)
- v2 result: **6,976,451 raw → 642,558 merged** — explosion.

**Root cause of v2 explosion:**
`max_ep=150` with no relative cut: a 50 px crossing track has nearest endpoint
≈ 25 px < 150 px → passes the cut. Beam-parallel crossing tracks dominate.

**Fix — relative endpoint cut (`max_ep_frac`):**
Two-component endpoint cut:
- Absolute: `ep < max_ep` (150 px)
- Relative: `ep < max_ep_frac × track_length` (0.5)

A genuine vertex track starts at the vertex → ep ≈ 0 px → always passes.
A crossing track: ep ≈ length/2 → relative cut rejects it.

- v3 result (+ `max_ep_frac=0.5`): **1,754,298 raw → 221,278 merged** ✓

**Spatial distribution map** (`scripts/vertex_map.py`):
![Vertex spatial map](docs/vertex_map.png)

The 45×45 FOV grid structure is visible. Bright clusters mark higher beam exposure areas.

---

## 2026-05-10 — Visual inspection; angular spread filter; run traceability; v4 run

### Visual inspection and teacher data (crop tool)

Built `scripts/crop_vertices.py` — 3-panel strip crops per vertex:
**RAW** (min projection across all z-slices, contrast-stretched) |
**FOG-REMOVED** | **BINARY**.

Min projection: dark tracks accumulate regardless of depth → shows all tracks in view.
Edge tick marks + 1 px centre dot mark the computed vertex position.

Inspected 30 crops from v3 (`n_tracks 5–12, n_slices ≥ 20, seed=7`):

| Category | Count | Crop indices |
|---|---|---|
| Emulsion artifact (crack / blob) | 7 | 003, 007, 011, 013, 025, 026, 030 |
| Good teacher (real particle tracks) | 23 | — |
| **Reaction vertex candidates** | **5** | **004, 017, 021, 023, 027** |

**Key finding**: high `n_slices` does NOT guarantee genuine vertices.
Emulsion artifacts (cracks, large blobs) persist across ALL slices → high `n_slices`.

**Event types confirmed:**

✓ **True reaction vertex** — multiple thin tracks radiating from a point at varied angles.
Seen reliably at n_tracks ≈ 8+. Large angular spread.

![True star vertex example](docs/n08_05_V00001395_n8_sl26.png)

△ **Track crossing** (false positive, minor) — long beam-parallel tracks crossing.
Dominant at n_tracks = 3–4. Largely suppressed by `max_ep_frac`.

✗ **Emulsion artifact fake** (false positive, major at n_tracks ≥ 15) — large crack or
blob survives `noise_amax=100 px²` cutoff. Its edges are detected by Hough as
near-parallel lines → fake high-multiplicity vertex with small angular spread.

![Heavy-particle fake vertex example](docs/n16_07_V00000437_n28_sl28.png)

Examples: `n11_01_V00000670_n15_sl25.png` (two thick tracks),
`n16_07_V00000437_n28_sl28.png` (thick track with kink),
`n16_08_V00001222_n24_sl29.png` (thick curved track).

### Angular spread filter

Implemented `min_angle_spread` in `find_vertices()`.
Uses doubled-angle circular statistics for line directions in [0°, 180°):
maps θ → exp(2iθ), computes mean resultant length R,
spread = arccos(R) / 2.

- n=34 artifact vertex: `angle_spread = 14.8°` → removed by threshold ≥ 15°.
- Genuine reaction vertex: large spread (tracks point in many directions).
- Set `--min-angle-spread 20.0` for KEKCC runs.

**Preprocessing fix needed (not yet done):**
Root cause of artifact fakes: `noise_amax=100 px²` only removes blobs ≤ 100 px².
Large artifacts (cracks, area >> 1000 px²) pass through unchanged → Hough detects edges.
Fix: add `noise_amax_upper` to `preprocess()` (e.g. 5000 px²) to remove large blobs.
Requires full re-run of `e07analyze` on KEKCC.

### Run traceability system

Added `e07fullscan/utils/run_info.py`.
Every output now carries:

| Field | Content |
|---|---|
| `run_id` | `YYYYMMDD_HHMMSS_<git_hash>` — unique per invocation |
| `script` | Script filename |
| `timestamp` | ISO-8601 datetime |
| `python` | Python version |
| `params` | All CLI arguments |

Stored as `<stem>_run.json` sidecar (parquet) or `run_params.json` (image dir),
and embedded in PyArrow schema metadata (`run_meta` key).

Read back:
```python
import json, pyarrow.parquet as pq
meta = json.loads(
    pq.read_table("results/vertices.parquet")
    .schema.metadata[b"run_meta"]
)
print(meta["run_id"])   # e.g. 20260510_165200_b0ec81f
print(meta["params"])
```

Scripts updated: `find_vertices.py`, `merge_vertices.py`,
`crop_vertices.py`, `vertex_map.py`.

### v4 vertex run (min_angle_spread=20°)

KEKCC array job 74625453 — 135 jobs, all DONE.
Output: `results/vertex_chunks_v4/` → `results/vertices_merged_v4.parquet`.

| n_tracks_max ≥ | v3 (spread=0°) | v4 (spread≥20°) | reduction |
|---|---|---|---|
| all | 221,278 | 207,259 | −6% |
| 5 | 127,178 | 102,178 | −20% |
| 8 | 13,180 | 8,542 | −35% |
| 10 | 4,639 | 2,143 | −54% |
| 15 | 987 | 337 | −66% |
| 20 | 215 | 91 | −58% |

Filter is most aggressive at high n_tracks_max, as expected
(artifact fakes have small angular spread).

---

## 2026-05-10 — v4 crops inspection; specials_x20 teacher events; integration tests

### v3 vs v4 crop comparison

Generated 30 crops from both v3 (`results/vertex_crops_teacher/`) and
v4 (`results/vertex_crops_v4/`) with identical parameters
(`n_tracks 5–12, n_slices≥20, seed=7`).

Because the underlying parquet files differ (v4 has 207k vs v3 221k merged),
the same random seed draws different vertices.
Qualitative comparison: v4 crops had noticeably fewer large-blob artifacts;
the high-n fake vertices with tightly clustered parallel lines were reduced.

Discussion: `n_slices` was previously thought to be a reliability metric
("more z-slices = more real"), but visual inspection shows emulsion cracks
persist across ALL slices → high `n_slices` is not a purity guarantee.

### specials_x20 teacher events

User provided 13 confirmed double-hypernuclei (or candidate) events at
`/gpfs/group/had/sks/Users/shuhei/work/specials_x20/`:

```
D005, D013, IBUKI, IRRAWADY, KISO, MINO, NAGARA,
T004, T004_3body, T004_center,
T011, T011_100, T011_200
```

Image format: plain PNG files (`0000.png`, `0001.png`, …) + `image.json`.
JSON format is identical to SPNG format except `Path` is a plain filename
rather than `file.spng&offset&length`.

`SpngReader` was extended to detect the format from the presence of `&` in
the Path field (`length=-1` sentinel for plain PNGs).

Pixel scale from `AffineP2S[0]`: 0.00028889 mm/px = **0.289 μm/px** —
identical to fullscan. Microscope settings confirmed compatible.

Z-spacing: ~3 μm/slice (vs ~1.5 μm/slice in fullscan) — factor 2 difference,
but `zpj_half=4` still gives ±12 μm range which is sufficient.

**Pipeline results on specials (all slices, min_angle_spread=0):**

| Event | Tracks | Best n | Spread |
|---|---|---|---|
| IBUKI | 39,563 | 10 | 31.9° |
| NAGARA | 61,711 | 9 | 23.2° |
| MINO | 39,858 | 18 | 30.2° |
| KISO | 38,256 | 11 | 42.4° |
| IRRAWADY | 33,943 | 10 | 38.7° |
| D005 | 97,737 | 13 | 35.5° |
| D013 | 91,253 | 12 | **13.4°** |
| T004 | 141,982 | 10 | **18.0°** |
| T011 | 26,202 | 10 | **8.2°** |

**Key finding**: D013, T004, T011 have angular spread < 20° at their
best vertex. This means the v4 `min_angle_spread=20°` production filter
would reject their primary vertex candidate.

Discussion: This does not necessarily mean the filter is wrong.
Possible explanations:
1. The "best n" vertex found is NOT the actual reaction vertex —
   could be a different feature. The true vertex may have larger spread.
2. These events genuinely have low spread (e.g. forward-boosted topology).
3. The vertex-finding algorithm is reconstructing only part of the star.

Decision: integration tests use `min_angle_spread=0` to validate the
pipeline independently of the production filter. The filter setting
is a separate optimization problem that requires ground-truth vertex positions.

**Vertex positions are NOT at image centre** (dist_center = 229–981 px).
The specials are NOT centred on the vertex; the vertex is somewhere in the
2048×2048 FOV. Cannot use "near centre" as a pass criterion in tests.

### Integration test suite (`tests/test_specials.py`)

Added `tests/test_specials.py` with two `@pytest.mark.slow` test types:

1. `test_special_reader_loads` — all 13 events, loads first/last slice,
   checks shape. Verifies reader extension works for plain PNG format.

2. `test_special_vertex_detected` — runs full track finding + vertex finding
   on each event, asserts `n_tracks_max >= 5` somewhere in the image.
   Parameters: `min_angle_spread=0, beam_angle_cut=0` (conservative, format-agnostic).

Slow tests skip by default (`pytest`); run explicitly with `pytest -m slow`.
Conftest: `tests/conftest.py` implements this via `pytest_collection_modifyitems`.
Marker registered in `pyproject.toml`.

Tested: `test_special_reader_loads` → 13/13 PASSED (3s).
`test_special_vertex_detected[IBUKI]`, `[T011]`, `[T011_100]`, `[T011_200]` → PASSED.

---

## Open Questions / Next Steps

- [x] **Ground truth positions**: recorded in `tests/specials_gt.json` (2026-05-12).
- [x] **Root cause of vertex miss**: grid-hash clustering bug — fixed with KDTree
      union-find (2026-05-13). All 9 specials events now PASS position test.
- [x] **v5 vertex run on KEKCC**: complete (2026-05-13). New results in
      `results/vertices_merged_v5.parquet`. See 2026-05-13 entry below.
- [ ] **2D analysis investigation**: per-slice analysis with ±2–4 slice
      superimposition + contrast improvement (CLAHE). Discussed 2026-05-13;
      keep current method but prototype the 2D approach for comparison.
- [ ] **Preprocessing fix**: add `noise_amax_upper` to `preprocess()`;
      requires full re-run of `e07analyze` on KEKCC.
- [ ] **Expand teacher data**: 5 reaction vertex candidates from 30 crops is too few;
      inspect 100–200 crops from updated vertex results.
- [ ] **Track re-analysis**: re-run `e07analyze` with `px_scale=0.29` to fix
      `grain_density` (currently 10× too low).
- [ ] **Grain density as PID**: once corrected, distinguishes α / slow proton / MIP.
- [x] **Two-vertex search**: `find_vertex_pairs()` + `scripts/find_pairs.py`
      implemented (2026-05-13). v5 run: 5,059 candidates (p_ntracks≥10) in
      1,153 views. See 2026-05-13 entry for details.
- [ ] **width_px filter**: `mean(width_px) < threshold` at vertex to reject
      thick heavy-track fakes.
- [ ] **Dip angle improvement**: only ~2% of tracks span >1 slice currently.

---

## 2026-05-11 — Vertex candidate maps; ground truth strategy; indentation fix

### Vertex candidate map generation

Generated all-candidates overlay maps for IBUKI, D013, T004, T011
(`results/specials_crops/*_all_vertices_map.png`):
- Green circles: vertices with spread ≥ 20°, radius ∝ n_tracks
- Yellow circles: vertices with spread < 20°
- n ≥ 7 vertices labelled with n value
- Background: min projection over all z-slices (all tracks visible)

**Key finding (critical)**: Visual inspection showed that ALL of the
pipeline's top-candidate vertices (highest n_tracks near image centre)
were **2-track crossings** — not reaction vertices. The true reaction
vertex was NOT the highest-n candidate.

T011 was the only event where a pipeline candidate (at pixel (994,983),
dist_center=50px) was close to the true vertex — described as "mettya oshii"
(very close but not exact).

This means the current pipeline cannot reliably identify the true reaction
vertex in specials events, even with centre-restricted search. Root cause
is not yet clear — candidates include high track density creating spurious
high-n intersections, and the geometric intersection algorithm not favouring
the true star topology.

### Ground truth collection strategy

Decided to collect true reaction vertex pixel positions directly from the
expert (user), using a dedicated interactive tool rather than inferring
from the pipeline output.

Added `scripts/click_vertex.py`:
- Displays min projection (all z-slices) of a specials event
- User clicks on the true reaction vertex
- Pixel coordinates (x, y) printed to terminal
- Supports both single PNG and directory (auto min-projection)

Next step: user identifies true vertex positions for each event →
record in `tests/specials_gt.json` → add position-based integration tests
that assert the pipeline finds a vertex within tolerance of the known position.

### Code quality: indentation rule fix

CLAUDE.md specifies 2-space indentation. Audit found that 13 source files
in `e07fullscan/` and `tests/` were using 4-space indentation.
All converted to 2-space. All 48 non-slow tests pass after conversion.

Affected files: `clustering/__init__.py`, `clustering/_cluster.py`,
`clustering/_vertex.py`, `merge/cli.py`, `server/__init__.py`,
`server/app.py`, `server/cli.py`, `server/results.py`,
`tracking/_finder.py`, `tracking/_track.py`,
`tests/test_clustering.py`, `tests/test_linking.py`,
`tests/test_results_viewer.py`.

## 2026-05-12 — Ground truth click session; caveats

Ran `scripts/click_vertex.py` interactively on specials_x20 events.
Expert (user) clicked on the true reaction vertex for each event.
Results saved as JSON files under `results/specials_vertex_click/`.

| File | Image | Clicks saved |
|------|-------|-------------|
| T011_0025.json | T011/0025.png | 2 (clicks 1,3 of 3) |
| IBUKI_0010.json | IBUKI/0010.png | 4 (all) |
| D005_0100.json | D005/0100.png | 2 (all) |
| D013_0100.json | D013/0100.png | 2 (all) |
| IRRAWADY_0011.json | IRRAWADY/0011.png | 3 (all) |
| KISO_0010.json | KISO/0010.png | 5 (all) |
| MINO_0028.json | MINO/0028.png | 2 (all) |
| NAGARA_0012.json | NAGARA/0012.png | 3 (all) |
| T004_0100.json | T004/0100.png | 1 (all) |

**Important caveats (user note):**
1. Click positions are approximate, not pixel-exact. Do not treat these
   coordinates as ground truth with sub-pixel accuracy.
2. Candidates far from the image centre may look vertex-like but are
   confirmed NOT to be double-track (reaction) vertices. Distance from
   centre is a useful negative signal.

Next step: use these approximate positions as loose ground truth to
evaluate pipeline candidates (e.g. within 50–100 px tolerance), keeping
the caveats above in mind when setting acceptance thresholds.

### Ground truth JSON and position+Z test

Saved `tests/specials_gt.json` with:
- XY pixel position per event (averaged over near-center clicks)
- Z coordinate (μm) from `reader.z_positions()[slice_idx]` using the
  slice number in the click filename (e.g. T011/0025.png → slice 25)
- Tolerance: `tolerance_xy_px=200`, `tolerance_z_um=30`

Key observation: all ground-truth Z values are within ±0.4 μm of 0,
confirming that the specials scans are centered on the vertex in Z.

Added `test_special_vertex_position` to `tests/test_specials.py`:
- Runs full pipeline including `merge_vertex_slices`
- Checks if any merged candidate is within 200 px XY AND 30 μm Z
  of the ground-truth position
- Currently expected to fail for most events (only D005 passes):
  the pipeline finds 2-track crossings rather than the true star vertex

Pipeline result vs ground truth (200 px XY tolerance):

| Event | True vertex | Pipeline's nearest candidate | dist XY |
|-------|-------------|------------------------------|---------|
| D005 | (1020,1023) | (1024,1021) n=12 | **3px** ✓ |
| KISO | (1096,1028) | (970,1144) n=9 | 171px (candidate within 200px?) |
| T004 | (1023,1038) | (881,992) n=11 | 149px |
| T011 | (992,984) | (813,1113) n=10 | 221px |
| NAGARA | (1020,1021) | (1151,1225) n=7 | 243px |
| IRRAWADY | (1010,1018) | (826,861) n=9 | 241px |
| D013 | (998,990) | (833,1321) n=10 | 370px |
| MINO | (1016,1018) | (725,829) n=11 | 348px |
| IBUKI | (982,968) | (936,1385) n=10 | 419px |

The `test_special_vertex_position` tests document the gap between current
pipeline capability and ground truth — passing them is the improvement target.

Updated `scripts/click_vertex.py` to record Z information (slice index and
z_um from `reader.z_positions()`) when a specific slice file is given.

---

## 2026-05-13 — KDTree clustering fix; pipeline status script; Japanese diary

### Root cause identified: grid-hash clustering bug

The previous intersection clustering in `_vertices_in_group` assigned each
point to a 25 px grid cell by hashing `gx * 100003 + gy`. Two points
straddling a cell boundary could be < 25 px apart yet land in different
clusters. For a star vertex with n tracks producing n(n-1)/2 intersection
points scattered over ~25–50 px, the grid split them into sub-clusters with
n_tracks < 3 → rejected by `min_tracks`. This silently missed the true vertex.

**Fix**: replaced grid hash with `cKDTree.query_pairs(eps_px)` + union-find
(path-compressed). All points within eps_px are guaranteed to merge.

### Verification on all 9 specials events (production cuts, KDTree fix)

Explicit post-fix run confirmed 9/9 PASS:

| Event | n | dist XY | Z |
|-------|---|---------|---|
| T011 | 9 | 2 px | −0.1 μm |
| IBUKI | 14 | 3 px | 0.2 μm |
| D005 | 12 | 5 px | 0.4 μm |
| MINO | 10 | 22 px | 0.0 μm |
| NAGARA | 7 | 25 px | −0.1 μm |
| IRRAWADY | 7 | 158 px | −0.3 μm |
| KISO | 9 | 171 px | −0.1 μm |
| T004 | 11 | 178 px | 0.2 μm |
| D013 | 12 | 185 px | −0.1 μm |

All within 200 px XY and 30 μm Z tolerance, all n ≥ 5.
`test_special_vertex_position` confirmed passing for all 9 events.

### Full slow test suite result (2026-05-13)

`pytest -m slow tests/test_specials.py` — **35/35 passed** (1 h 38 min):
- `test_special_vertex_detected`  13/13 ✓
- `test_special_vertex_position`   9/9  ✓  (new; ground-truth position test)
- `test_special_reader_loads`     13/13 ✓

### Pipeline status script

Added `scripts/status.py` (zero arguments):
```
python scripts/status.py
```
Shows track chunk count, merged parquet row count, vertex chunk progress,
and KEKCC running jobs in one compact view. Replaces multi-flag monitor.py
for quick status checks.

### Japanese development diary

Added `ANALYSIS_ja.md` — Japanese mirror of this file, updated in sync.
`CLAUDE.md` updated to require keeping both files current.

---

## 2026-05-13 — v5 full-scan vertex run; ΛΛ vertex pair search

### v5 KEKCC run (KDTree fix applied)

Re-ran vertex finding for all 135 chunks with the KDTree union-find fix.
Parameters identical to v4 (`min_tracks=3`, `min_angle_spread=20°`,
`beam_angle_cut=15°`, `eps=25 px`, `max_ep=150 px`).

| Metric | v4 | v5 | Change |
|--------|-----|-----|--------|
| Raw candidates | 1,091,300 | 1,091,300 | same |
| Merged vertices (min_slices=2) | 207,259 | 212,777 | +2.7% |
| n_tracks_max ≥ 5 | 102,178 | 114,089 | +11.7% |
| n_tracks_max ≥ 10 | 2,143 | 3,933 | **+83.5%** |

The dramatic improvement in high-multiplicity vertices confirms the bug fix:
the old grid-hash was splitting star vertices' intersection clusters, while
KDTree correctly merges all intersections within `eps_px`. The effect is
largest for high-n events precisely because they had more intersections to
be split across grid boundaries.

Vertex map: `results/vertex_map_v5.png` (n_tracks≥5, n_slices≥3; 102,889
candidates shown).

### Z scale discovery

Z values in `z_mean` column are in **mm** (scanner stage unit), not μm.
- z_step ≈ 0.003 mm = 3 μm per slice
- Full-scan z range: −0.259 to −0.048 mm (≈ 211 μm total emulsion thickness)
- Specials views span 0.177 mm = 177 μm per event

This matters for the dz filter in vertex pair search: threshold of 0.010 mm
(= 10 μm ≈ 3 z-steps) selects same-layer vertex pairs.

### ΛΛ topology vertex pair search

Implemented `e07fullscan.clustering.find_vertex_pairs()` and
`scripts/find_pairs.py`.

Search criteria:
- Same view
- XY separation: 30–167 px (90–500 μm)
- Primary: n_tracks_max ≥ min_n_primary
- Secondary: n_tracks_max ≥ 3, n_slices ≥ 2
- dz < 0.010 mm (10 μm; both vertices at same emulsion depth)

v5 results (min_n_primary=5):

| n_primary cut | Pairs | Views |
|---------------|-------|-------|
| ≥ 5 | 95,353 | 2,025 |
| ≥ 8 | 14,760 | 1,901 |
| ≥ 10 | 5,059 | 1,153 |
| ≥ 15 | 1,423 | 250 |

With p_ntracks ≥ 10: 5,059 candidates in 1,153 views is a manageable
number for semi-manual scanning. The 9 confirmed ΛΛ events from specials_x20
should all appear in this list (pending cross-matching with full-scan view IDs).

**Next step**: generate two-vertex crop images (both primary and secondary
visible) for the top candidates sorted by primary n_tracks_max, for manual
scanning to identify true ΛΛ events.

After requiring primary n_tracks_max >= secondary (labeling fix) and
Z proximity (dz < 0.010 mm = 10 μm):

| n_primary cut | Pairs | Views |
|---------------|-------|-------|
| ≥ 5 | 73,751 | 2,025 |
| ≥ 10 | 4,353 | 1,153 |
| ≥ 15 | 1,125 | 250 |

### Connecting track search

Implemented `scripts/filter_pairs_by_track.py` to require a connecting
track (Λ flight path) with an endpoint within `tol` px of BOTH vertices.

Tolerance sensitivity (p_ntracks ≥ 10 pairs in one chunk):
- tol=10 px: 9.5% of pairs pass
- tol=20 px: 52.4% pass
- tol=30 px: 90.5% pass

tol=20 px (≈ 6 μm) chosen for balance: enough to account for vertex
position resolution (~5-15 px), but still discriminating.

Full-scan results (tol=20 px):

| Filter | Pairs | Views |
|--------|-------|-------|
| All pairs (p≥5) | 73,751 | 2,025 |
| + connecting track (tol=20 px) | 25,842 | 2,023 |
| + p≥10 | 1,838 | 819 |
| + p≥15 | 494 | 186 |

**1,838 connected pairs with p_ntracks≥10 in 819 views** — manageable
for semi-manual inspection (~2.2 pairs/view).

### Golden ΛΛ candidate selection

Added a physics-motivated multi-level filter:
1. XY distance: 90–500 μm (30–167 px)
2. Primary vertex: n_tracks_max 10–20
3. Secondary vertex: n_tracks_max 3–8 (consistent with ΛΛ decay star)
4. Connecting track exists (tol=20 px)
5. Scored by: `p_ntracks × s_ntracks / log(1 + dist_px)`

Result: **1,220 golden candidates in 709 views** (saved as
`results/vertex_pairs_v5_golden.parquet`).
- 399 views with exactly 1 pair (highest priority)
- 202 views with 2 pairs

Top candidate profile (score-ranked):
- p_ntracks ≈ 16–20, s_ntracks ≈ 6–8
- dist_um ≈ 150–400 μm
- p_nslices typically 5–15 (well-confirmed primary)

**Next step**: crop images for the top 200 golden candidates; manual
inspection to confirm ΛΛ topology (connecting track, star morphology).

## 2026-05-13 — Angle spread propagation into vertex pair output

### angle_spread column propagation

The `merge_vertex_slices()` function already preserves `angle_spread_best`
and `angle_spread_max` in the merged vertex DataFrame (added earlier today).
However, `find_vertex_pairs()` was not forwarding these values into the
pair output. Fixed: the function now propagates `p_angle_spread` and
`s_angle_spread` (using `angle_spread_best`) into each pair record.

The pipeline was re-run end-to-end:
1. `find_pairs.py` → 73,751 pairs with angle_spread columns
2. `filter_pairs_by_track.py` (tol=20 px) → 25,842 filtered pairs
3. Golden selection → 1,220 pairs (same as before, now with spread data)

### angle_spread statistics in golden candidates

All vertices passed the production cut min_angle_spread=20°, so all
values are ≥ 20°. Distribution:

| Vertex | mean | median | 25th pct | 75th pct |
|--------|------|--------|----------|----------|
| Primary   | 31.8° | 32.4° | 26.7° | 37.1° |
| Secondary | 29.3° | 28.9° | 24.2° | 34.0° |

Secondary vertices show slightly lower spread than primaries, consistent
with fewer prongs (3–8 vs 10–20). The distributions overlap strongly;
angle_spread alone is not a sharp discriminator at these statistics.

Low-spread fractions among golden candidates:
- p_angle_spread < 25°: 18.4% (225/1220)
- s_angle_spread < 25°: 29.4% (359/1220)
- both < 25°: 5.4% (66/1220)

Vertices with both < 25° may warrant closer inspection as possible
ghost vertices (tracks nearly parallel → not a real star topology).

### Crop image regeneration

`crop_pairs.py` updated to display `sp=XX°` next to n_tracks label
for both primary and secondary vertices. The top-200 golden crops were
regenerated in `results/pair_crops_v5_golden/` with angle_spread labels.

**Open questions**:
- [ ] Can angle_spread in combination with s_ntracks provide a cleaner
      background rejection? (ΛΛ decay: expect moderate spread 25–45°)
- [ ] Are the 66 both-low-spread pairs truly ghosts, or can they be
      genuine events with aligned decay geometry?

### CLAHE contrast enhancement for crop images

Added CLAHE (Contrast-Limited Adaptive Histogram Equalization, clipLimit=2.0,
tileGridSize=8×8) to `crop_pairs.py` before annotation. Applied to the
z-projected image to enhance local contrast so tracks and vertex structure
are more visible during manual inspection.

Effect on rank-1 candidate: raw mean=183 → CLAHE mean=160 (contrast stretched).
All 200 golden crops regenerated with CLAHE in `results/pair_crops_v5_golden/`.

### noise_amax_upper: large artifact removal in preprocessing

Added `noise_amax_upper` parameter to `preprocess()` in
`e07fullscan/tracking/_finder.py`. When set > 0, removes binary blobs
with area > threshold from the processed image before Hough line detection.

Purpose: suppress large silver grain clusters, emulsion folds, and cosmic
muon track residuals that are larger than any single track segment but
still pass the current small-blob noise filter. Default = 0 (disabled) for
backward compatibility. Can be enabled via YAML config: `noise_amax_upper: N`.

A full re-run of `e07analyze` would be needed to propagate this change to
the chunk parquet files; this is a future task for KEKCC.

### Teacher data expansion

Generated 200 new teacher crops from v5 merged vertices (n_tracks≥8,
n_slices≥4) in `results/vertex_crops_teacher_v5/`. Combined with the
existing 60 crops in `results/vertex_crops_teacher/`, the total teacher
dataset is now 260 crops for visual training/validation.

## 2026-05-13 — Pixel scale correction, v6 pipeline, and KISO specials investigation

### Critical: pixel scale was 10× wrong

The production constant `PX_SCALE = 3.0` μm/px in `_vertex.py` was wrong by
a factor of 10. The correct value, confirmed from the SPNG scanner JSON
(`AffineP2S = [0.00028889, ...]`) and from scan geometry (2048 px × 0.29 =
594 μm ≈ 0.5 mm FOV spacing), is **0.29 μm/px**.

Consequence: the old v5 pair search used d=30–167 px ≈ 9–48 μm — an order of
magnitude too small for ΛΛ events (expected 90–500 μm). All v5 "golden"
candidates were at the wrong scale.

Fix: `_PX_SCALE_UM = 0.29`, `_D_MIN_PX = 310` (90 μm), `_D_MAX_PX = 1724`
(500 μm) in `e07fullscan/clustering/_vertex.py`.

### v6 pipeline run with corrected scale

Re-ran the full pipeline with corrected distance cuts:

| File | Count | Notes |
|---|---|---|
| `vertex_pairs_v6.parquet` | 1,200,346 | all pairs d=90–500 μm |
| `vertex_pairs_v6_prefilter.parquet` | 43,013 | p:10–20, s:3–8 |
| `vertex_pairs_v6_filtered.parquet` | 97 | connecting-track filter tol=30 px |

The connecting-track filter (requiring a Hough track spanning P→S) gives 97
pairs but all turn out to be heavy ionising particle tracks (a single track
that happens to stop or scatter). This filter selects the wrong topology: it
finds heavy particle tracks rather than ΛΛ pairs. Root cause: only 0.47% of
Hough segments are ≥310 px (Λ flight path) because each z-slice only captures
a 3-μm window, keeping segments short (≈50–100 px typical). The connecting-
track filter is **abandoned** for v6 and will be rethought.

### Coordinate system characterisation

Comparing stage positions between the KISO special event scan (NLAB-PC06) and
the fullscan (NLAB-PC13), the correct pixel-to-stage mapping for fullscan is:

```
stage_x = view_cx - (px_x - 1024) × 0.00029 mm   (x axis mirrored)
stage_y = view_cy + (px_y - 1024) × 0.00029 mm   (y axis same)
```

with `view_cx, view_cy` = the stage centre of the view (mm), taken from
the `x, y` fields of the view JSON.

Verification: applying this convention to KISO in V00001173 (view centre
1.499, 13.001):
- Primary expected stage (1.748, 12.882) → pixel (95, 617)  ✓ (distance 666 px = 193 μm to secondary matches KISO P-S distance exactly)
- Secondary expected stage (1.668, 13.048) → pixel (441, 1186)  ✓ (nearest detected vertex: (432, 1241) n=6 at 56 px)

### KISO specials matching result

KISO is the **only** special event with stage coordinates within the fullscan
plate range (1.748, 12.882 mm). Other specials (D005, D013, IBUKI, etc.) were
scanned on different microscope setups with different coordinate origins and
cannot be matched without additional calibration.

For KISO in view V00001173:
- **Primary (95, 617)**: 6–9 Hough lines detected per z-slice with hough_ml=25
  (lengths 25–50 px). With the production threshold hough_ml=50, these tracks
  are below the minimum length and the vertex is **not detected**.
  Reason: near-surface vertex (~top 2–3 z-slices, z ≈ −0.076 mm) with short
  track projections due to steep dip angles.
- **Secondary (432, 1241) n=6 sp=24.8**: detected and in the vertex catalog.
  Distance from expected KISO secondary position: 56 px ≈ 16 μm.

**KISO is NOT in v6_prefilter pairs** because the primary vertex was not
detected. The secondary appears in v6 pairs but only paired with unrelated
primaries (distance 90–308 μm to those primaries).

Root cause of KISO primary miss: `hough_min_line = 50 px` (14.5 μm). Near the
emulsion surface, track projections in a 3-μm z-slice can be as short as
25–40 px for tracks with dip angles > ~11°. Lowering `hough_min_line` to
25–30 px should allow detection.

Side effect risk: shorter line threshold increases noise hits. Needs careful
benchmarking against n_tracks / angle_spread distributions.

### Action items

- [ ] Lower `hough_min_line` to 30 px and re-run vertex finding on views
      near confirmed specials to test recovery
- [ ] Determine coordinate offsets for non-KISO specials (requires calibration
      data or overlap of known features)
- [ ] Rethink connecting-track filter: grain-density cut on primary→secondary
      direction, or directional isolation cut at primary vertex instead
- [ ] Consider line-intersection vertex finder as a supplement to the current
      endpoint-convergence finder (needed for high-dip-angle tracks)

---

## 2026-05-13 — Cross-view vertex pair finder; KISO recovery

### Discovery: KISO primary straddles view boundary

The KISO event was expected at stage (1.769, 12.883) for the primary and
(1.668, 13.048) for the secondary. In the fullscan layout:

| View | Center (mm) | KISO primary px | KISO secondary px |
|---|---|---|---|
| V00001173 | (1.499, 13.001) | (93, 617) — near LEFT edge | (441, 1186) → detected (432, 1241) |
| V00001174 | (2.000, 13.001) | (1821, 617) — near RIGHT edge | (2169, 1186) — outside |

The KISO primary is at pixel x ≈ 93 in V00001173 (2048-wide view), only
93 px from the left edge. Tracks extending toward lower x are cut off by
the view boundary. With hough_ml=50, the vertex finder detects at most n=5
near this position (high-n vertex (354,1204) n=11 is 86 px away and is
actually the secondary of a different interaction).

In V00001174, the primary expected position is at pixel (1821, 617), near
the right edge. With hough_ml=30, a vertex (1854, 630) n=5 sp=35.6 is found
at 37 px from the expected position (stage distance 10 μm).

**Conclusion: KISO spans the V00001173 / V00001174 view boundary.** A single-
view vertex pair finder cannot recover it.

### Cross-view pair finder: `scripts/find_crossview_pairs.py`

Implemented a new script that:
1. Computes stage (mm) coordinates for every vertex using Convention C.
2. Builds a cKDTree on stage coordinates.
3. For each candidate primary (n ≥ min_n_primary), searches all vertices in
   **different views** within [d_min_mm, d_max_mm] stage distance.
4. Applies Z-separation cut (max_dz_mm; default 0.200 mm for cross-view
   since dip angle at ~20° gives dz ≈ 66 μm for a 193-μm flight).

Key difference from intra-view finder: the "primary must have ≥ n_tracks as
secondary" constraint is removed, because at view boundaries the physical
primary appears weaker (tracks cut off).

Default max_dz_mm was raised from 0.010 mm (intra-view) to 0.200 mm for
cross-view, because the KISO primary-secondary dz = 70.2 μm (dip angle ~21°).

### KISO cross-view detection result

Running on `vertices_merged_v5.parquet` (hough_ml=50):

```
P=(432,1241) n=6 sp=24.8 in V00001173   (physical secondary, higher n)
S=(1888,716) n=5 sp=23.5 in V00001174   (physical primary, truncated)
dist = 171.5 μm   (expected 193 μm, error = 11%)
dz   = 70.2 μm    (consistent with dip angle ~21°)
```

**KISO IS recovered as a cross-view pair**, but with roles swapped (the
physical secondary has higher n than the physical primary, so it appears as
"P" in the output). The distance error of 22 μm comes from vertex position
errors (~35 μm for the truncated primary, ~16 μm for the secondary).

With hough_ml=30 in V00001174, the primary candidate improves to
(1854, 630) n=5 sp=35.6 at 36 px from expected, giving:
```
cross-view distance = 198.0 μm   (expected 193 μm, error = 2.6%)
```

### Config change: hough_ml 50 → 30

Updated `config/default.yaml`: `hough_ml: 50` → `hough_ml: 30`
(8.7 μm at 0.29 μm/px). This improves detection of short track segments at
surface vertices and view-boundary primaries. The full pipeline (2025 views ×
58 slices) must be re-run on KEKCC to apply this to the vertex catalog.

### Cross-view background and scale

Running `find_crossview_pairs.py` on v5 catalog with min_n=5/3, d=90–500 μm,
max_dz=200 μm gives 18,822,640 cross-view pairs. A systematic background is
observed: the pair pattern (px ≈ 430,1240) in one view ↔ (px ≈ 1890,720) in
the adjacent x+1 view with d ≈ 165–177 μm recurs across many view-row
positions. This arises because the same relative stage offset corresponds to
similar pixel positions in every pair of adjacent views — likely a heavy-
particle track (beam particle or knock-on electron) traversing the view
boundary, creating fake star-vertex signatures on both sides.

To suppress: require max(n_primary, n_secondary) ≥ 10 and
min(n_primary, n_secondary) ≥ 6 and both sp ≥ 30°. This gives ~67,717 pairs.

### Action items (updated)

- [x] Lower `hough_min_line` to 30 px (done in config/default.yaml)
- [ ] Re-run full pipeline on KEKCC with hough_ml=30 to regenerate
      chunk parquets and vertices_merged_v6.parquet
- [ ] Run `find_crossview_pairs.py` on v6 catalog to find cross-view ΛΛ pairs
- [ ] Determine coordinate offsets for non-KISO specials
- [ ] Develop background suppression for cross-view pairs (n, sp cuts)
- [ ] Implement KISO verification comparison image (specials vs fullscan crop)

---

## 2026-05-14 — n-ordering bug fix; all 9 specials detected; cross-view filter study

### Bug fix: `find_vertex_pairs` n-ordering constraint

Removed the line `if nt[pi] < nt[si]: continue` from
`e07fullscan/clustering/_vertex.py` (`find_vertex_pairs`).

**Why this existed:** The original intent was to enforce "primary has more
tracks than secondary", which is physically motivated by the Ξ⁻ stopping star
having more prongs than the Λ decay. **Why it was wrong:** At view boundaries
(KISO) and in multi-body decays, the secondary can accumulate more visible
tracks than the truncated primary. Removing the constraint is safe — the
role labels (primary/secondary) are now defined purely by topology (n_tracks
threshold), not by relative ordering.

**Impact:** v7 pairs regenerated from `vertices_merged_v5.parquet` with
correct distance range (90–500 μm): **1,479,220 intra-view pairs** (up from
v6: 1,200,346 = +23% from unblocked P.n<S.n pairs).

### Specials pipeline test: all 9 events detected

Ran the full pipeline (find_tracks → find_vertices → merge_vertex_slices →
find_vertex_pairs with max_dz_mm=0.200) on all 9 confirmed specials_x20
events. All events produce candidate pairs.

| Event | Vertices | n_max | Pairs | Notes |
|-------|----------|-------|-------|-------|
| D005 | 358 | 15 | 48,887 | — |
| D013 | 331 | 15 | 27,367 | — |
| IBUKI | 281 | 14 | 24,170 | — |
| IRRAWADY | 158 | 11 | 4,828 | — |
| KISO | 192 | 11 | 9,491 | true pair found (see below) |
| MINO | 304 | 19 | 33,562 | — |
| NAGARA | 221 | 9 | 12,236 | — |
| T004 | 380 | 14 | 47,555 | — |
| T011 | 135 | 14 | 3,919 | — |

**KISO true pair recovered in specials image:**
```
P=(1108,1090) n=6 nsl=4  z=-0.225 mm   (62 px from gt primary)
S=(751,1589)  n=9 nsl=13 z=-0.211 mm   (11 px from gt secondary)
dist = 178 μm   (expected 194 μm, error 8%)
dz   = 0.014 mm
```
Before the n-ordering fix this pair was blocked (P.n=6 < S.n=9). After the
fix it is found. The 8% distance error is consistent with vertex centroiding
uncertainty at the primary vertex, which has only 4 z-slices visible (short
secondary vertex due to the multi-body decay topology).

**Challenge:** Each specials image produces 4,000–50,000 pairs. The true pair
is buried in this background. Pair ranking is required.

### Full-scan context: scan area covers only KISO

The current vertex catalog (`vertices_merged_v5.parquet`) covers
x_mm = [−0.001, 22.001], y_mm = [0.002, 22.000] — a 22×22 mm² area.
Only **KISO** falls within this area (view_x=1.75, view_y=12.88 mm).
The other 8 specials are at distances > 58 mm from the scan boundary.

KISO is confirmed in the full-scan cross-view pairs catalog:
```
P = V00001173 (354,1204) n=11 nsl=7 sp=42.3°
S = V00001174 (1888,716) n=5  nsl=6 sp=23.5°
dist = 152 μm  (expected 194 μm, error 22%)
dz   = 0.026 mm
```
The 22% distance error is because the v5 catalog was built with `hough_ml=50`
(50 px min line length), which truncates the primary vertex. A rerun with
`hough_ml=30` is expected to recover the primary at its true position.

### Cross-view pair background suppression

Applied progressive cuts to the 18.8M cross-view pairs:

| Cut | Pairs | KISO |
|-----|-------|------|
| All | 18,822,640 | 132 |
| adjacent-view only | 14,800,258 | 132 |
| + p_ntracks 6–20, p_sp≥30° | 4,208,859 | 48 |
| + s_ntracks≥4, s_sp≥20° | 3,326,423 | 48 |
| + dist 90–250 μm, dz≤0.030 mm | 211,692 | 8 |
| + p_nslices≥5, s_nslices≥4 | **109,376** | **7** |

KISO survives all cuts. The 7 KISO candidates (V00001173→V00001174) include
the true pair and 6 background pairs sharing the same primary or secondary.
The true pair has the highest p_ntracks*p_angle_spread combination.

### v5 pairs: critical error (wrong distance range)

Discovered that `vertex_pairs_v5.parquet` was generated with
d_min=30 px (8.7 μm) and d_max=167 px (48 μm) — accidentally using the
`hough_ml` values as the pair-distance range. All v5 pairs are useless for
ΛΛ analysis. v6 and v7 use the correct 90–500 μm range.

### Intra-view connected pairs: v6_filtered

Applied connecting-track filter (`filter_pairs_by_track.py`) to v6 pairs:
**97 pairs** surviving from 1.2M, with p_ntracks 10–19, p_sp 20–45°,
dist 90–307 μm. KISO not included (cross-view). These 97 pairs are the
priority candidates for visual inspection.

### Action items (updated)

- [x] Fix n-ordering constraint in `find_vertex_pairs` (done 2026-05-14)
- [x] Regenerate v7 intra-view pairs with n-ordering fix
- [x] Confirm KISO detected in specials image after fix (P.n=6, S.n=9)
- [x] Document v5 distance-range bug
- [x] Cross-view filter study: 18.8M → 109K with KISO survival
- [ ] Re-run full pipeline on KEKCC with hough_ml=30
- [ ] Run find_crossview_pairs.py on v6 catalog
- [ ] Apply connecting-track filter to cross-view pairs
- [ ] Visual inspection of 97 intra-view connected pairs
- [ ] Determine coordinate offsets for non-KISO specials

### v7_filtered: connecting-track filter の結果

`filter_pairs_by_track.py` を v7 (min_n_primary=10、90-500μm) に適用:

```
v7_filtered:  540 ペア  (min_n_primary=10, tol=50px)
  ΛΛ範囲 (p_n:6-20, s_n:3-15, sp>=20):  398 ペア (368 ユニーク)
    ─ v6_filtered と共通:  97 ペア  ← 全 v6 候補が回収された ✓
    ─ n順序修正で新規:    301 ペア
  強候補 (p_sp>=30, s_sp>=25, p_n>=8, s_n>=4):  120 ユニークペア
```

v6_filtered の97ペアが全て v7_filtered に含まれる: n順序修正は既存の
候補を失わずに、新たに301ペアを追加した。

**トップ候補 (score = P.n + S.n):**

| view | P pos | P n | P sp | S pos | S n | S sp | dist |
|------|-------|-----|------|-------|-----|------|------|
| V00000670 | (1288,1135) | 17 | 30° | (988,1222) | 11 | 40° | 91μm |
| V00000794 | (564,641) | 14 | 31° | (790,417) | 13 | 36° | 92μm |
| V00001842 | (1541,1337) | 16 | 35° | (1870,1186) | 11 | 40° | 105μm |
| V00000441 | (1160,1387) | 16 | 38° | (982,1132) | 9 | 39° | 90μm |
| V00000871 | (508,1490) | 15 | 37° | (1008,1799) | 10 | 26° | 170μm |
| V00000851 | (1840,1441) | 19 | 32° | (1499,1279) | 5 | 39° | 110μm |

dist 中央値 ≈ 108μm は物理的に妥当 (ΛΛ の飛行距離: 90-300μm)。

**次のステップ:** 120 強候補の視覚的検査 (crop_pairs.py) で真の ΛΛ
事象と重核相互作用バックグラウンドを区別する。

## 2026-05-14 — Connecting-track annotation and Tier A candidate selection

### Connecting-track property annotation

All 123 strong candidates annotated with connecting-track properties
using `scripts/annotate_pairs.py` (tolerance 50 px):

- `conn_mean_intens`: mean intensity of the best connecting track
- `conn_grain_density`: grain density of connecting track
- `conn_angle_diff`: angle between track direction and P→S vector
- `conn_len_ratio`: track length / dist_px

Key findings:
- `conn_angle_diff` ≈ 0° for virtually all candidates (all connecting
  tracks are co-linear with P→S, not useful as discriminator)
- `conn_mean_intens`: mean=16.8, std=6.1; only 2 pairs exceed 35
  (rank2 at 37.1 and rank11 at 39.8)
- Visual false positives (rank1,4,5) have moderate intens (25.5, 13.9,
  12.4) — connecting-track intensity alone cannot identify heavy-particle
  fakes because the heavy-particle track may be split into multiple short
  segments in tracking, and the "connecting track" found may be a
  secondary (delta ray) rather than the primary particle

### Tier A / B / C classification

Applied multi-criteria tiers to the 123 strong candidates:

| Tier | Criteria | Count |
|------|----------|-------|
| A | s_n≥8, p_sp≥30°, s_sp≥28°, d=90-400μm, I<38 | 25 |
| B | s_n≥6, p_sp≥28°, s_sp≥25°, d=90-500μm | 53 |
| C | rest | 45 |

Tier A corresponds most closely to the known specials parameter range
(all 9 specials have s_n=9–13, both sp>25°). The hough_ml=50 truncation
means we might be missing tracks, so s_n≥8 rather than s_n≥9 is used.

Output files:
- `results/vertex_pairs_v7_strong_ann.parquet`: 123 pairs with conn props
- `results/vertex_pairs_v7_tier_a.parquet`: 25 Tier A pairs
- `results/pair_crops_v7_ann/`: 123 annotated PNG crops (I= printed)
- `results/pair_crops_v7_tier_a/`: 25 Tier A crops (priority inspection)

### Tier A top candidates

| # | View | Pn | Psp | Sn | Ssp | d(μm) | I | Notes |
|---|------|----|-----|----|-----|-------|---|-------|
| 1 | V00000670 | 17 | 30° | 11 | 40° | 91 | 25.5 | — |
| 2 | V00000794 | 14 | 31° | 13 | 36° | 92 | 37.1 | visual ΛΛ ◎ |
| 3 | V00001842 | 16 | 35° | 11 | 40° | 105 | 13.4 | visual ΛΛ ○ |
| 4 | V00000441 | 16 | 38° | 9 | 39° | 90 | 16.5 | visual ΛΛ ○ |
| 5 | V00000102 | 11 | 44° | 11 | 35° | 97 | 16.8 | visual ΛΛ ○ |
| 8 | V00001832 | 10 | 37° | 11 | 36° | 101 | 20.6 | — |
| 10 | V00001542 | 12 | 39° | 10 | 40° | 228 | 8.0 | — |

Visual inspection summary (top 10 from previous session):
- rank2, rank6(=tier4), rank8(=tier5): confirmed ΛΛ candidate topology
- rank1, rank4orig, rank5orig: heavy-particle false positive (visual)
  (note: rank mapping shifted after Tier A re-ordering)

### Next steps
1. Visual inspection of 25 Tier A crops in `pair_crops_v7_tier_a/`
2. Cross-view connecting-track filter for 109,376 xview pairs
   (Ξ⁻ track at view edge: primary has track ending at right edge,
   secondary has track starting from left edge of adjacent view)
3. KEKCC rerun with hough_ml=30 (full 22×22 mm² → full scan area)

## 2026-05-14 — Cross-view connecting-track filter (filter_xview_pairs.py)

### Method

`scripts/filter_xview_pairs.py` checks for boundary-crossing tracks:
- **Primary view**: track with one endpoint within 60 px of P vertex,
  the other endpoint within 300 px of the view edge facing the secondary
- **Secondary view**: track with one endpoint within 60 px of S vertex,
  the other endpoint within 300 px of the view edge facing the primary

View-edge direction inferred from VX/VY indices via the stage-to-pixel
convention: stage_x = view_cx − (vx_px − 1024) × 0.00029 mm, so
higher VX ↔ higher stage_x ↔ lower pixel_x. This means:
- Secondary at higher VX → P exits via LEFT (x<300), S enters via RIGHT (x>1748)
- Secondary at lower  VX → P exits via RIGHT, S enters via LEFT
- Analogous for VY

### Results

Input: 29,408 pairs (pre-cuts: p_n≥8, s_n≥4, p_sp≥28°, s_sp≥20°,
d≤250μm, dz≤0.028mm)

| Stage | Count |
|-------|-------|
| Pre-cut input | 29,408 |
| After boundary-crossing filter | 2,986 |
| After ΛΛ range (p_n≤20, s_n≤15) | 2,952 |
| Strong (s_n≥5, p_sp≥30°, s_sp≥22°, d≤230μm) | 1,596 |

KISO true pair (P=(354,1204) n=11 sp=42° → S=(1888,716) n=5 sp=23°,
d=152μm, dz=0.026mm) survives all stages ✓ (rank 988/2952 in ΛΛ-range).

Output files:
- `results/vertex_pairs_xview_v1_conn.parquet`: 2,986 pairs
- `results/vertex_pairs_xview_v1_conn_ll.parquet`: 2,952 ΛΛ-range
- `results/vertex_pairs_xview_v1_strong.parquet`: 1,596 strong candidates

Top cross-view strong candidates (by score = P.n × S.n / log(d_px)):

| # | P view | S view | Pn | Psp | Sn | Ssp | d(μm) | dz |
|---|--------|--------|----|-----|----|-----|-------|-----|
| 1 | V00001748 | V00001749 | 19 | 40° | 15 | 23° | 198 | 0.000 |
| 2 | V00000749 | V00000750 | 17 | 32° | 14 | 26° | 183 | 0.005 |
| 6 | V00001222 | V00001223 | 16 | 35° | 12 | 30° | 161 | 0.001 |
| 7 | V00000336 | V00000337 | 18 | 42° | 11 | 33° | 212 | 0.000 |
| 10 | V00000871 | V00000872 | 15 | 37° | 13 | 37° | 210 | 0.003 |
| KISO | V00001173 | V00001174 | 11 | 42° | 5 | 23° | 152 | 0.026 |

### Summary of candidate catalog (2026-05-14)

| Catalog | Count | KISO ✓? | Notes |
|---------|-------|---------|-------|
| vertex_pairs_v7_strong.parquet | 123 intra-view | N/A | KISO is cross-view |
| vertex_pairs_v7_tier_a.parquet | 25 | — | priority inspection |
| vertex_pairs_xview_v1_strong.parquet | 1,596 | ✓ | cross-view, s_n≥5 |
| vertex_pairs_xview_v1_conn_ll.parquet | 2,952 | ✓ | full ΛΛ-range |

---

## 2026-05-14 — v6 pipeline: intra-view and cross-view pair finding

### Context

v6 tracking used hough_ml=30 (correct, vs hough_ml=50 in v5), producing
70.8M tracks (3× more than v5's 24M). Vertex merging gave 237,029
vertices (+11% vs v5's 212,777).

### Intra-view pairs (vertex_pairs_v6)

Run:
```
python scripts/find_pairs.py \
  --input  results/vertices_merged_v6.parquet \
  --output results/vertex_pairs_v6.parquet \
  --d-min  310 --d-max 1724 \
  --min-n-primary 5 --min-n-secondary 3 \
  --max-dz-mm 0.010
```
Result: **1,851,442 pairs** (+25% vs v7's 1,479,220 from hough_ml=50
vertices). Next step: apply connecting-track filter and strong
selection, analogous to v7_filtered → v7_strong pipeline.

### Cross-view pairs (vertex_pairs_xview_v6)

Raw generation produced **23,474,643 pairs** (90–500 μm, dz≤0.200 mm).

Applying the same pre-filter as v1 (adjacent-view, p_sp≥30°, s_sp≥20°,
p_nslices≥5, s_nslices≥4, p_ntracks≥6) gives **2,219,749 pairs**, which
is 20× more than v1's 109,376. Investigation:
- Unique primary-quality vertices: v6 30,585 vs v5 26,207 (+17%)
- Unique secondary-quality vertices: v6 127,613 vs v5 115,121 (+11%)
- Pairs per primary: v6 72.1 vs v1 4.7 — discrepancy unexplained

The large pair count makes the boundary-crossing filter impractical at
that scale (~50 hours estimated). Applied stricter pre-cuts that
preserve KISO-like signal (KISO: P.sp=42°, P.n=11, S.sp=23°, S.n=5,
d=152μm):

| Cut | Count |
|-----|-------|
| Adjacent-view + p_sp≥30°, s_sp≥20°, p_nsl≥5, s_nsl≥4, p_n≥6 | 2,219,749 |
| + p_sp≥35°, p_n≥8, d≤400μm | 204,405 |

Applied boundary-crossing filter to 204,405 pairs (in progress as of
2026-05-14). KISO would pass all cuts (p_sp=42°>35°, p_n=11>8,
d=152μm<400μm).

Output files:
- `results/vertex_pairs_xview_v6.parquet`: 23,474,643 raw pairs
- `results/vertex_pairs_xview_v6_filtered.parquet`: 2,219,749 pre-filtered
- `results/vertex_pairs_xview_v6_prefiltered.parquet`: 204,405 strict pre-filter
- `results/vertex_pairs_xview_v6_conn.parquet`: **5,113 pairs** (conn filter complete)

### Intra-view filter and strong selection (completed 2026-05-14)

Parallelized via KEKCC array jobs (15 intra + 20 xconn), split by chunk-group
to keep per-job memory under 2 GB (queue hard limit: 4 GB). Round-robin
slicing caused TERM_MEMLIMIT (each job loaded all 135 chunks); chunk-group
splitting fixed this.

| Stage | Count | Notes |
|-------|-------|-------|
| vertex_pairs_v6.parquet | 1,851,442 | raw |
| vertex_pairs_v6_filtered.parquet | 641 | conn-track filter (min_n=10) |
| vertex_pairs_v6_ann.parquet | 641 | + conn-track properties |
| vertex_pairs_v6_strong.parquet | 169 | p_sp≥30°, s_sp≥25°, p_n≥8, s_n≥4, d≤400μm |
| vertex_pairs_v6_tier_a.parquet | 168 | + conn_intens<38 |

v5/v7 comparison: strong 169 vs 123 (+37%), xview_conn 5,113 vs 2,986 (+71%).

Crops for visual inspection: `results/pair_crops_v6_strong/` (169 images).

---

## 2026-05-14 — Shared discussion log for parallel agents

Claude Code is also running in the repository, so we introduced
`discussion.md` as an append-only coordination log. The goal is to keep active
assumptions, edited files, and open questions visible while preserving the
chronological diary style in `ANALYSIS.md` and `ANALYSIS_ja.md`.

Initial Codex note to Claude records the observed dirty working tree and asks
for clarification on the v6 cross-view excess: whether the large candidate
increase is best explained by the lower Hough minimum length, view-neighboring
logic, or coordinate/indexing conventions. The note also proposes recording
intended output filenames before script changes to avoid overwriting
intermediate products.

---

## 2026-05-14 — Japanese discussion log added

Created `discussion_ja.md` as a Japanese counterpart to `discussion.md` after
the user requested it. The file mirrors the initial Codex-to-Claude
coordination message in Japanese and explicitly asks Claude to append current
tasks, assumptions, edited files, and planned output filenames.

README coordination guidance was updated to mention both logs. This preserves
the English log for concise cross-agent handoff while giving Japanese notes a
dedicated place consistent with the repository instructions.

---

## 2026-05-14 — Discussion monitoring added to agent rules

The user requested that the discussion-log monitoring rule be promoted into
both `AGENTS.md` and `CLAUDE.md`. Added an Agent Coordination section to both
files requiring agents to check `discussion.md` and `discussion_ja.md` before
repository work, before editing shared files, and before final reporting.

The rule keeps both discussion logs append-only and asks agents to record
intended inputs, outputs, generated directories, and file ownership before
launching jobs or changing scripts. README was updated to point to the
mandatory rule.

---

## 2026-05-14 — Direction change: individual vertex detection

Until now the pipeline focused on finding ΛΛ Primary/Secondary pairs.
The user decided to abandon the paired-topology requirement and instead detect
individual reaction vertices directly (nuclear stars, α-decay, single Λ,
ΛΛ primaries — any visible vertex topology).

Rationale: pair topology enforces a specific signal model and leaves many
signal vertices undetected.  A direct vertex catalogue gives a more complete
view of the emulsion events.

### Quality filter on merged vertices

Applied cuts to `results/vertices_merged_v6.parquet` (237,029 vertices):

| Cut | Value |
|-----|-------|
| n_tracks_max | ≥ 8 |
| angle_spread_best | ≥ 28° |
| n_slices | ≥ 4 |

Output: `results/vertices_quality_v6.parquet` — **10,750 vertices**.

### Crop generation

Generated image crops for the top 500 candidates sorted by n_tracks_max
(descending).  Output directory: `results/vertex_crops_v6/` (500 PNG files).

Range covered: n_tracks_max 82 → 15, across the full 45×45 view grid.

Crops are named:
```
NNN_V{view_id}_L0_VX{vx}_VY{vy}_..._n{ntracks}_sl{nslices}_z0_x{px}_y{py}.png
```

Next step: visual inspection of the 500 crops to assess background
contamination and identify candidate vertices for follow-up measurement.

---

## 2026-05-27 10:28 JST — Ranking change: n_tracks_max → sp×nsl; visual inspection

### Dead end: n_tracks_max ranking

Sorting by `n_tracks_max` alone was counterproductive: the top-500
(`vertex_crops_v6/`) was dominated by beam pile-up and heavy-particle
fakes (n_tracks_max 82→15). KISO's nearest candidate (n=8, sp=36°,
nsl=9) was not in the top-500.

### New ranking: score = angle_spread_best × n_slices

Adopted `score = angle_spread_best × n_slices` as the ranking criterion,
following joint Codex/Claude discussion (2026-05-14 21:56 JST). Rationale:
- Rewards star-like angular spread (genuine multi-prong topology)
- Rewards cross-slice persistence (not a single-layer artefact)
- Does not directly reward high track multiplicity (avoids heavy-particle bias)

New crop set: `results/vertex_crops_v6_sp_nsl/` (500 images).
Script: `crop_vertices.py --sort-by sp_nsl --n-samples 500`.

### Visual inspection result (2026-05-27)

User inspected all 500 crops. **Dramatic improvement** over the previous
n_tracks_max ranking:

- Reaction vertex-like images (multi-prong stars) increased significantly
- Remaining background contamination — two types:
  1. **Large debris / grid points**: emulsion artefacts or scanner grid
     features misidentified as vertices
  2. **Unrelated track crossings**: two unrelated tracks crossing at a
     point; not a physical reaction vertex

**Conclusion**: sp×nsl confirmed as the ranking score going forward.

### Next steps

- Assess whether debris and crossing-track backgrounds can be suppressed
  by additional quality cuts (e.g. minimum angular spread between the two
  most-separated tracks, or a circularity/isotropy measure)
- Generate labelled catalog from visual inspection results
- `specials_x20/` is a symlink to `../specials_x20` (external reference
  image data for the 9 confirmed special events; read-only, not a pipeline
  output — resolved in discussion 2026-05-27)

---

## 2026-05-27 21:31 JST — Thesis-informed ranking review

The user added `S.H.Hayakawa_D.pdf`, the related doctoral thesis. Codex
reviewed the relevant parts of Chapter 4 and Chapter 5 for the current
vertex-preprocessing discussion.

Key interpretation: the thesis event categorization did not use a single
star-like score. It used topology plus track context: distorted vs straight
incoming track, charged-particle emission, and whether a beam track was
visible at the vertex. Hypernuclear production is classified as a
`sigma-stop`, i.e. a stopping negative track with endpoint distortion and
charged-particle emission, not simply as a high-multiplicity star.

This supports the current recall-first preprocessing policy. The Hough-based
features are useful for broad image retrieval, but they do not yet encode
the physics-relevant endpoint context. High `n_tracks_max`, high
`n_slices`, and visually strong nuclear stars should not dominate the only
ranking, because known hypernuclear events such as KISO can be less visually
extreme.

Next algorithmic direction: keep multiple preprocessing channels
(broad reaction-like, hypernuclear-recall, background-rich reserve), and
move toward a graph/topology representation with candidate vertices,
track endpoints, track-segment edges, incoming-track straightness or
distortion, outgoing prongs, beam-track evidence, and nearby secondary
vertices.

---

## 2026-05-28 — Score-formula quantification; two-channel ranking decision

Quantified the score alternatives proposed on 2026-05-27 against the one
special inside the fullscan plate range (KISO), to decide the ranking score
for the recall-first preprocessing stage. Discussion: discussion.md
2026-05-28 15:48–17:01 JST.

### KISO rank under each score (vertices_quality_v6, N=10,750)

KISO anchor = its nearest match in V00001173 (sp=41.4°, nsl=7, n=9).

| Score              | KISO rank   | percentile | top-500 needs |
|--------------------|-------------|------------|---------------|
| `sp` alone         | **798**     | 7.4%       | nsl≥4         |
| `sp × sqrt(nsl)`   | 4,475       | 41.6%      | nsl≥12        |
| `sp × log(nsl)`    | 4,227       | 39.3%      | nsl≥11        |
| `sp × min(nsl,10)` | 5,947       | 55.3%      | nsl≥10        |
| `sp × nsl` (prev)  | 6,188       | 57.6%      | nsl≥14        |

### Key finding: capping/damping nsl does NOT rescue KISO

The `sp × min(nsl,10)` formula we had been leaning toward barely helps
(rank 5,947 vs 6,188). KISO's nsl=7 is *below* the cap of 10, so min(7,10)=7
gives it no boost; the cap only damps the 35% of vertices with nsl>10. Any
score that multiplies by nsl penalizes a genuine localized reaction vertex
whose tracks span only a moderate z-depth. Only dropping nsl from the
ranking (`sp` alone) brings KISO into a usable candidate budget (top-800).

Dropping nsl does **not** flood the list with shallow artefacts: the sp≥41.4°
pool (816 vertices) has a healthy n_slices spread (4-7: 24%, 8-10: 33%,
11-13: 24%, ≥14: 19%) and only 4% at n_tracks_max≥17, since the nsl≥4 quality
floor is already applied.

### Two-list diagnostic (the persistence bias, made visible)

- `hough_recall_sp`    = rank by `sp`, nsl≥4 floor only
- `hough_broad_sp_nsl` = rank by `sp × nsl` (previous sole ranking)

Top-N overlap: 500→15%, 1000→23%, 2000→36%. Top-500 composition:

| feature           | recall_sp | broad_sp_nsl |
|-------------------|-----------|--------------|
| sp median         | 43.2      | 38.2         |
| nsl median        | 10        | 18           |
| nsl ≥14           | 19%       | **100%**     |
| n_tracks_max ≥17  | **4%**    | **14%**      |

`broad_sp_nsl` top-500 is fully saturated at nsl≥14 and carries 14% of the
n≥17 background-rich stratum; `recall_sp` keeps a balanced nsl spread and
much less heavy-star contamination.

### Decision: keep both as separate ranked views (not replacement)

Joint Codex/Claude agreement (discussion 17:01 JST):

- **`hough_recall_sp`** — `sp`-dominant, nsl≥4 floor only, n≥17 as a
  background flag → the **hypernuclear-recall route** for this recall-first
  stage. No nsl multiplier (even a weak one) is added, since nsl is the
  source of the bias being avoided here.
- **`hough_broad_sp_nsl`** — the previous `sp × nsl` ranking, retained for
  broad reaction-like / heavy-nuclear-star surveying.

This **scopes** the 2026-05-27 conclusion ("sp×nsl confirmed as the ranking
score going forward") to the *broad* channel only; it is no longer the sole
ranking. (Earlier diary entries are left intact per lab-notebook policy.)

### Next steps

- Step-5 (noise-removal) compatibility artifact before any new large crop
  production: one fullscan view + KISO + T011 (smallest low-sp special)
  through `e07fullscan/tracking/_finder.py::preprocess()`; compare
  post-noise foreground fraction, connected-component area quantiles, and
  matched projections. Interpretation kept conservative — raw-intensity
  mismatch alone does not disqualify specials_x20.
- Low-sp specials (T011/T004/D013): bounded Hough failure-mode diagnostic
  around the clicked GT vertex (4 categories) before any graph-branch call.

---

## 2026-05-28 — Step-5 compatibility check: specials_x20 vs fullscan-image

Validated whether specials_x20 can serve as a sanity-check anchor for the
conventional Hough branch, by comparing both sources *after the same step-5
preprocessing* (the shared boundary before the Hough/graph split). Per the
2026-05-28 scope lock, **the visual-review server was not used; the batch
`e07fullscan.tracking._finder.preprocess()` was called directly**, so the
statistics match exactly what the batch pipeline sees (noise_amax_upper=0).
Script: `scripts/step5_compat.py`; outputs in `results/step5_compat/`.

Sources: fullscan view V00001173 (holds the KISO catalog match), KISO, and
T011 (smallest low-sp special). For each, the find_tracks ±4 mean
z-projection at the center slice was fed to preprocess().

| metric                 | fullscan V00001173 | KISO        | T011         |
|------------------------|--------------------|-------------|--------------|
| shape / dtype          | 2048² uint8        | same        | same         |
| n_slices               | 58                 | 60          | 50           |
| dz (µm/slice)          | 3.00               | 3.00        | 3.00         |
| px scale (µm)          | 0.29 (config)      | 0.289       | 0.289        |
| raw proj mean / std    | 182.5 / 39.3       | 98.0 / 54.7 | 145.6 / 19.8 |
| post-step5 fg fraction | 7.27%              | 6.64%       | 4.17%        |
| CC count               | 2548               | 1353        | 1532         |
| CC area median (px²)   | 62                 | 125         | 55           |

### Findings

- **Geometry is identical** across sources (2048² uint8, 3.0 µm/slice,
  0.289 µm/px). (Note: fullscan view JSON stores an identity AffineP2S; its
  physical scale comes from config, 0.29 µm/px.)
- **Raw intensity differs substantially** (acquisition exposure/contrast;
  NLAB-PC13 vs PC06) — but, conservatively, this alone does not disqualify
  specials_x20 as reference data.
- **After step-5 the representations converge**: foreground fractions all
  land in the 4–7% band, connected-component counts/areas are the same order,
  and track-like structures visibly survive in all three (montage.png). The
  normalizing mechanism is fog removal (GaussianBlur − img) followed by
  per-image Otsu, which adapts the threshold and absorbs the raw-brightness
  difference.

### Conclusion

specials_x20 is usable as a sanity-check anchor for the conventional Hough
branch *after the same step-5 preprocessing*; no extra normalization beyond
step-5 is required for qualitative/sanity use. Open expert question:
NLAB-PC06 vs PC13 optics/illumination/camera equivalence — but step-5 absorbs
the main concern (raw brightness).

### Note on a dormant duplication (to fix before debris tuning)

Code review (discussion 2026-05-28) found that `server/app.py` reimplements
fog/Otsu/noise in `_process()`/`_collect_stats()` and **omits the
`noise_amax_upper` branch** present in `tracking.preprocess()`. Currently
harmless because `noise_amax_upper = 0`, but the viewer would silently
under-clean relative to batch once large-blob removal is enabled. Agreed
(Codex/Claude) to extract a branch-neutral preprocessing module and have both
tracking and server call it — as a separate behavior-preserving task (with an
old-vs-new regression test), not mixed with scoring/compatibility work.

### Next steps

- Low-sp specials (T011/T004/D013): bounded Hough failure-mode diagnostic
  around the clicked GT vertex (tracks lost in preprocessing / Hough line
  extraction miss / vertex merge fails / vertex exists but low scalar score).

---

## 2026-05-28 — Low-sp specials failure-mode diagnostic

Walked the conventional Hough branch at the clicked GT vertex for the three
low-sp confirmed specials (T011/T004/D013), to decide whether their low angle
spread is a preprocessing/extraction/association failure or a genuine
topology limit. Batch functions called directly; design agreed with Codex
(discussion 2026-05-28 19:04/19:11). Script: `scripts/lowsp_diag.py`; crops
in `results/lowsp_diag/`. find_tracks v6 config (hough_ml=30), find_vertices
defaults (min_angle_spread=0), merged over ±12 slices, two radii (200/300 px).

| event | fg@R200 | endpts/body in R200 | near-GT spread R200/R300 | single vtx | merged vtx (±12) |
|-------|---------|---------------------|--------------------------|------------|------------------|
| T011  | 6.4%    | 38 / 38             | 32.4° / 31.6°            | d=3px n=5 sp=16.7 | d=10px n=10 nsl=8 sp=12.7 |
| T004  | 6.0%    | 17 / 17             | 22.6° / 34.0°            | d=2px n=6 sp=2.5  | d=11px n=10 nsl=10 sp=8.2 |
| D013  | 7.4%    | 48 / 48             | 29.8° / 29.0°            | d=14px n=13 sp=31.8 | d=9px n=13 nsl=12 sp=31.8 |

### Findings

- **No cat 1/2/3 hard failure for any of the three.** Structure survives
  preprocessing (fg 6–7% at GT), Hough lines are extracted with endpoint
  support at GT (endpoints_in == body_in → not through-going; min_body
  0.4–7.5 px), and a vertex forms within tolerance (2–14 px). The low-sp
  issue is at the spread/scoring step, not the image/Hough/association-
  existence step.

- **D013 is not actually low-sp.** Its GT vertex is detected cleanly
  (sp=31.8°, n=13, nsl=12) and would rank fine under sp-recall. The
  historical "D013 sp=13.4°" (2026-05-10) measured a *different* best-n
  vertex, not the true GT vertex. D013 leaves the low-sp problem set.

- **T011 is a fragmentation / under-association artifact.** The crop shows a
  clear multi-prong star at GT and the near-GT endpoint-supported lines span
  32°, yet the detected vertex sp is only 12.7°. The 25 px clustering
  (eps_px) + endpoint cuts split the genuine star into a more-collinear
  sub-vertex; the angular diversity is present in the image but the scalar
  vertex sp under-captures it. Likely recoverable inside the Hough branch.

- **T004 is the genuine low-sp core.** Immediate vertex sp=2.5° (single) /
  8.2° (merged); near-GT spread 22.6° at R200 widening to 34° at R300 — a
  near-collinear core with prongs at larger radius (forward-boosted topology).
  The real graph-branch candidate.

### Implication

The recall worry about low-sp specials is largely a measurement/fragmentation
artifact (T011, D013), not a fundamental Hough-representation limit. Only T004
clearly needs the graph branch.

### Next steps

- Hough-branch test (before graph work): recompute vertex angle_spread over a
  wider endpoint-association radius, or merge adjacent sub-vertices within ~the
  GT tolerance before scoring, and check whether T011 recovers toward its 32°
  near-GT spread while T004 stays low. If T011 recovers, sp-recall ranking
  catches it without the graph branch.

---

## 2026-05-29 — T011 spread-recovery test: fragmentation confirmed

Tested the proposed Hough-branch fix from the 2026-05-28 low-sp diagnostic:
is T011's low vertex spread a clustering-fragmentation artifact? At the GT
slice, anchored at the detected vertex nearest GT, swept the endpoint-
association radius R and recomputed angle_spread over tracks whose nearest
endpoint lies within R. Script: `scripts/lowsp_spread_radius.py`; plot
`results/lowsp_diag/spread_vs_radius.png`. Batch functions called directly.

| event | detected sp | R=25 | R=50 | R=75 | R=100 | R=150 | R=200 |
|-------|-------------|------|------|------|-------|-------|-------|
| T011  | 16.7        | 28.5 | 34.3 | 34.6 | 32.5  | 33.1  | 32.4  |
| T004  | 2.5         | 3.1  | 3.7  | 5.6  | 21.5  | 24.2  | 22.6  |
| D013  | 31.8        | 29.2 | 27.2 | 31.7 | 32.3  | 33.1  | 30.1  |

### Findings

- **T011: fragmentation artifact, fully recoverable.** Spread reaches 28.5°
  at R=25 and ~34° at R=50, vs the detected scalar sp of 12.7–16.7°. The
  genuine multi-prong star sits right at the vertex; the 25 px intersection
  clustering split it into a collinear sub-vertex. A wider spread radius
  recovers it inside the Hough branch — no graph work needed for T011.
- **T004: genuine collinear core.** 3–6° within R≤75; only reaches ~22° at
  R≥100 by absorbing distant tracks, never cleanly clearing the sp=28 cut.
  The immediate vertex is genuinely near-collinear (forward-boosted) — a real
  graph-branch candidate.
- **D013: not low-sp** (≥27° at every radius) — positive control.

Net: of the three "low-sp" specials, D013 was a wrong-vertex mislabel, T011
is recoverable with a wider spread radius, and only T004 is a true low-sp
core. The recall concern about low-sp events is mostly a measurement artifact.

### Caveat before adopting a wider spread radius

The test shows wider-radius spread recovers signal (T011) but not its cost:
widening globally would also raise the spread of crossing-track / background
vertices and could hurt sp-recall purity. The signal side is validated; the
background side needs a catalog-level check before adoption.

### Next steps

- Measure the background cost: recompute wider-radius spread on a sample of
  broad-catalog n=8–10 vertices and count how many cross sp=28. If wider
  radius inflates background spread badly, keep the tight radius.
- T004: graph-branch candidate (pending Codex confirmation / other-z recheck).

---

## 2026-05-29 — Correction: T004 low-sp is algorithmic, physics label deferred

Correction to the 2026-05-28/05-29 low-sp entries (kept above per the
append-only lab-notebook policy; this entry qualifies them). Following Codex's
note (discussion 2026-05-28 22:06), the description of T004 as a
"forward-boosted topology" / sigma-stop overstated what the code shows.

Corrected position:

- **Factual (from code)**: T004's clicked GT vertex is detected within
  tolerance but its angular spread stays low (~2.5° immediate; only ~22° at
  R≥100 by absorbing distant tracks) and does not cleanly clear the sp=28
  quality cut. This is a genuine low-sp core in the Hough scalar
  representation, distinct from T011's clustering-fragmentation artifact.
  Algorithmically, T004 is the graph/topology-branch candidate among the
  three.
- **Deferred to expert (not from code)**: whether that low-sp core is
  physically a sigma-stop / forward-boosted hypernuclear topology is an
  emulsion-physics interpretation, not a code-derived fact. Flagged as a
  question for the user / domain expert, not asserted.

---

## 2026-05-29 — Background-cost of wider spread radius; T004 z-persistence

Closed the low-sp scoring thread with two bounded tests (batch functions
called directly; design agreed with Codex, discussion 2026-05-29 11:06).

### Background-cost check (`scripts/bg_cost_spread.py`)

Sampled 80 broad-catalog n_tracks_max 8–10 vertices from
vertices_merged_v6 (seed=7; 63 usable), recomputed anchor angle_spread at
R=25 (tight) vs R=50 (the T011-recovering radius), same method as the
2026-05-29 sweep.

| metric | R=25 | R=50 |
|--------|------|------|
| spread median | 29.6 | 32.2 |
| spread p90    | 38.4 | 38.2 |
| Δ(R50−R25) median / p90 | — | 2.2 / 15.4 |

- 27/63 below sp=28 at R=25; **10 of those (37%) promoted ≥28 at R=50**
  (16% of all). Top inflations are near-collinear backgrounds blown up by the
  wider radius (sp25 0.4→28.1, 1.3→38.1, 1.8→27.5).
- **Conclusion: do not adopt R=50 globally** — it promotes crossing/parallel
  backgrounds across the cut. Keep the tight radius.

Why T011 still recoverable without the global cost: at its true vertex anchor
T011 already reads 28.5° at R=25; its catalog sp was 12.7° only because the
25 px clustering split the star into an offset sub-vertex. The fix is a
targeted sub-vertex merge near the true vertex (recover at tight radius,
leave background untouched), not a global radius change.

### T004 z-persistence

Swept slices 92–108 around GT (z_slice 100). The vertex nearest GT
(dist ≤32 px) is low-sp at every slice (sp 2.5–7.4 at dist ≤18 px;
14.0 at slice 102 only because nearest is 271 px away). A few sp~32 vertices
sit 100–200 px from GT — separate structures, not the GT vertex. The low-sp
core persists across the z-neighborhood: **T004 is a robust graph-branch
candidate** (physics label deferred to expert).

### Scoring-thread conclusion (before code cleanup)

1. Hypernuclear-recall ranking = `sp` (no nsl multiplier; nsl≥4 floor only)
   [decided 2026-05-28].
2. Spread-association radius stays tight (R=25); not widened globally.
3. T011-type fragmentation → targeted sub-vertex merge, deferred to the
   post-cleanup Hough-branch implementation (not done now).
4. D013 removed from low-sp set; T004 = graph-branch candidate.

Next: code cleanup (branch-neutral preprocess extraction + server dedup +
diagnostics packaging), as a separate behavior-preserving task with an
old-vs-new regression test.

---

## 2026-05-29 — Code cleanup step 1+2: shared preprocessing extraction

Started the structural cleanup agreed with Codex (discussion 2026-05-28 17:22
/ 2026-05-29 14:28). Behavior-preserving; the analysis behavior of the v6
pipeline is unchanged under current config.

### Changes

- New module `e07fullscan/preprocess.py` (branch-neutral, the shared boundary
  before the Hough/graph split): `fog_remove`, `otsu_binarize`,
  `remove_noise` (single source of the 3-branch connected-component area
  filter), and `preprocess` = fog→Otsu→noise.
- `tracking/_finder.py`: local `preprocess` removed; imports and re-exports
  from `e07fullscan.preprocess` (callers using
  `from tracking._finder import preprocess` keep working). `fog_img` for
  intensity measurement now uses `fog_remove`, so fog removal has one
  implementation.
- `server/app.py`: `_process`/`_collect_stats` no longer reimplement
  fog/Otsu/noise; they call the shared functions. This **closes the dormant
  `noise_amax_upper` omission** (the server filter previously lacked the
  large-blob branch). Under default config (`noise_amax_upper=0`) server
  output is unchanged; the difference only appears once large-blob removal is
  enabled — the fix we agreed to make before debris tuning.

### Verification

- `tests/test_preprocess.py` (new): new `preprocess` is byte-identical to a
  frozen copy of the old `_finder.preprocess` (default and with
  `noise_amax_upper`), `remove_noise(amax_upper=0)` matches the old server
  2-branch filter, and `amax_upper>0` removes the large blob. 4/4 pass.
- `pytest -m "not slow"`: 52 passed, no regressions.

### Deferred (Codex sequencing)

- Step 3: move reusable diagnostic helpers (tracks_to_df, projection,
  TRACK_CFG, shared across step5_compat/lowsp_diag/lowsp_spread_radius/
  bg_cost_spread) under `e07fullscan/diagnostics/`, thinning the scripts.
- Step 4: targeted sub-vertex merge (the T011-type Hough-branch recall fix).

---

## 2026-05-29 — Code cleanup step 3: diagnostics packaging

Completed the structural cleanup. Behavior-preserving pure refactor of the
diagnostic scripts.

### Changes

- New `e07fullscan/diagnostics/` package (`__init__` + `_common.py`) holding
  helpers that were duplicated across the 4 diagnostic scripts: `TRACK_CFG`
  (v6 config), `DF_COLS`, `tracks_to_df`, `projection`, `find_tracks_cfg`.
- step5_compat, lowsp_diag, lowsp_spread_radius, bg_cost_spread thinned to
  import these; each keeps only its unique logic.
- CLAUDE.md updated: `diagnostics` added to subpackages, `preprocess` noted as
  the shared branch-neutral module.

### Verification

- `lowsp_spread_radius.py` re-run gives numbers identical to the 2026-05-29
  record (T011 R25=28.5/R50=34.3, T004 3.1/3.7, D013 29.2/27.2) — pure refactor.
- `pytest -m "not slow"`: 52 passed.

### Structural cleanup complete

- #1 branch-neutral `preprocess` extraction ✓
- #2 tracking + server call it; dormant `noise_amax_upper` omission closed ✓
- #3 diagnostics packaging; 4 scripts thinned ✓
- #4 targeted sub-vertex merge — deferred recall feature (not structural)

The shared step-5 boundary is now a single implementation used by both the
batch tracking path and the viewer, and the diagnostic scripts share one
helper module. Next analysis work (when resumed): the T011-type targeted
sub-vertex merge as a Hough-branch recall fix.

---

## 2026-05-30 — Cleanup: dead-code removal + package rename e07fullscan -> module

Continued the structural cleanup. Behavior-preserving; v6 analysis behavior
unchanged. Discussion 2026-05-29 20:32 / 2026-05-30 15:31.

### Dead code

- Removed `add_dip_angles` (clustering/_link.py): zero callers anywhere; also
  dropped the now-unused `import math`. No residual references; tests green.

### Package rename e07fullscan -> module

- User decision (the package is never imported externally, so a generic import
  name carries no practical collision/searchability cost).
- `git mv e07fullscan module`; rewrote `e07fullscan` -> `module` across all
  32 .py files (package, scripts, tests), pyproject.toml (distribution name,
  the 3 console entry points, packages.find), and README.md.
- CLI command names (e07view/e07analyze/e07merge) kept; only their module
  targets changed. No top-level run.py added (out of scope).
- Not pip-installed in this environment (runs via PYTHONPATH), so no reinstall
  needed; if installed elsewhere, re-run `pip install -e .` to refresh entry
  points.
- Past discussion/ANALYSIS entries keep `e07fullscan` as historical record.

### Verification

- `pytest -m "not slow"`: 52 passed.
- `lowsp_spread_radius.py` re-run reproduces the 2026-05-29 numbers (T011
  R25=28.5/R50=34.3, T004 3.1/3.7, D013 29.2) — rename is pure.

### Still to do (this cleanup thread)

- Quarantine legacy ΛΛ-pair code (find_vertex_pairs + 6 pair scripts) into
  module/clustering/_pairs.py and scripts/legacy/, done in the renamed tree.
- crop_vertices stale options (z_target/zpj_mode): mark/document or remove.

---

## 2026-05-30 — Cleanup: quarantine legacy ΛΛ-pair code

Continued the cleanup by isolating the legacy ΛΛ-pair path (superseded
2026-05-14 by individual vertex detection) so the active vertex path is easy
to see. Behavior-preserving. Discussion 2026-05-29 20:33.

### Changes

- Moved `find_vertex_pairs` (+ its ΛΛ topology constants) out of
  `clustering/_vertex.py` into `clustering/_pairs.py`. `clustering/__init__.py`
  re-exports it for back-compat with a comment marking it legacy. _vertex.py
  now contains only the active path (find_vertices, merge_vertex_slices).
- Moved the 6 ΛΛ-pair scripts (find_pairs, find_crossview_pairs,
  filter_pairs_by_track, filter_xview_pairs, annotate_pairs, crop_pairs) to
  `scripts/legacy/`, fixed their ROOT (`parents[1]` -> `parents[2]`), and
  added `scripts/legacy/README.md` documenting their provenance and run note.
  `scripts/` now lists only active individual-vertex / diagnostic / infra
  scripts.

### Verification

- find_vertex_pairs re-export identity holds; `pytest -m "not slow"` 52
  passed; legacy scripts compile and resolve ROOT to the repo root.
- Not deleted, per Codex: pair topology produced historical results and may be
  cited; deletion only after explicit user approval.

### Remaining in this cleanup thread

- crop_vertices stale options (z_target/zpj_mode): mark/document or remove.

---

## 2026-05-30 — Cleanup: crop_vertices stale options removed/marked

Final item of the cleanup thread. Behavior-preserving (crops still use the
all-slice minimum-intensity projection).

- Removed two unused internal functions in scripts/crop_vertices.py:
  `_load_zproject` and `_fog_remove_max` (no callers; main uses
  `_load_min_projection`). Removed the dead `z_target` local.
- `--zpj-half` / `--zpj-mode` CLI args are unused (never read from `args`).
  Per Codex (user-facing, mark if in doubt), kept them for CLI back-compat but
  marked their help text "(unused; crops use all-slice min projection)" and
  added a NOTE comment, rather than removing the flags.
- Compiles clean; no residual references; sys.path/SpngReader bootstrap still
  present in the surviving functions.

### Cleanup thread complete (pending Codex sign-off)

- dead code removed (add_dip_angles); crop stale functions removed
- package renamed e07fullscan -> module
- legacy ΛΛ-pair path isolated (clustering/_pairs.py, scripts/legacy/)
- active vertex path and active scripts are now easy to see
- pytest -m "not slow" green; deterministic diagnostics reproduce

---

## 2026-05-30 — Structure + analysis-flow diagrams

Produced two explanatory diagrams (outside README, as the user asked), built
with Graphviz, reflecting the post-cleanup structure. Codex signed off on the
cleanup (discussion 2026-05-30 15:46) and specified the 5 things the diagrams
should show; both are encoded.

- `docs/structure.dot` / `docs/structure.png`: file/package layout. module/
  subpackages with preprocess marked as the shared step-5 module and server as
  the viewer; scripts/ split into active / diagnostics / infra / legacy; config
  and tests shown as context. Colour key: active blue/green, viewer orange,
  legacy gray-dashed.
- `docs/analysis_flow.dot` / `docs/analysis_flow.png`: data flow. raw z-stack
  → shared preprocessing (steps 1–5, with the step-5 boundary labelled) →
  conventional Hough/vertex branch (find_tracks → find_vertices → merge →
  quality cut → sp / sp×nsl ranking → crops). The viewer is drawn as a side
  client calling the same preprocess/find_tracks; the legacy ΛΛ-pair path and a
  future graph/ML branch are dashed.

Regenerate with `dot -Tpng docs/<name>.dot -o docs/<name>.png`.

---

## 2026-05-30 — Coordination: persistent watcher memory rules

Updated `AGENTS.md` so stateless Codex watcher runs (`codex exec`, cron, or
tmux loops) can safely reconstruct context from repository files instead of
transient model memory.

- Refreshed the package section to `module` (renamed from `e07fullscan`) and
  listed the current subpackages plus shared `preprocess`.
- Added the simplification principle: prefer Occam's razor, reduce visible
  entry points and files, avoid new `scripts/` subdirectories, and keep
  diagnostics/legacy code out of the everyday operation surface.
- Added a startup memory rule: every session or watcher must read
  `AGENTS.md`, `CLAUDE.md`, `discussion.md`, `discussion_ja.md`,
  `ANALYSIS.md`, and `ANALYSIS_ja.md`.
- Reaffirmed Codex as discussion-main and Markdown-only editor; Claude remains
  responsible for implementation work.

---

## 2026-05-30 — Tooling: persistent Codex discussion watcher script

Added `scripts/codex_discussion_watch.sh` at the user's explicit request and
exception to allow a new shell script in `scripts/`.

- Runs a persistent loop suitable for tmux.
- Calls `codex exec` each tick with a prompt that rebuilds memory from
  `AGENTS.md`, `CLAUDE.md`, `discussion.md`, `discussion_ja.md`,
  `ANALYSIS.md`, and `ANALYSIS_ja.md`.
- Keeps Codex as discussion-main and Markdown-only by prompt.
- Uses `flock` to avoid overlapping runs and `timeout` to prevent a stuck
  Codex execution from blocking the watcher forever.
- Supports environment overrides: `ROOT`, `CODEX_BIN`, `INTERVAL_SEC`,
  `TIMEOUT_SEC`, `LOCK_FILE`, `LOG_DIR`, `LOG_FILE`.

Verification: `bash -n scripts/codex_discussion_watch.sh` passed and the file
was made executable.

Follow-up: the initial tmux run showed that `codex exec` does not accept
`--ask-for-approval`. Removed that option, re-ran `bash -n`, restarted the
detached `codex-discuss-watch` tmux session, and confirmed the watcher log
shows a successful no-op discussion check.

---

## 2026-05-30 — scripts-surface cleanup: run.py + slimmed scripts/

Reorganized the operation surface so scripts/ is no longer a confusing mix of
.py and .sh. User decisions: run.py-first; no new subdirectories in scripts/
(existing scripts/legacy/ kept). Behavior-preserving. Codex discussion
2026-05-30 17:00–17:45.

### Changes

- New repo-root `run.py`: single operation surface; subcommands delegate via
  subprocess to existing scripts / module entry points (track, view,
  merge-tracks, vertices, merge-vertices, crops, review, map, click,
  submit-tracking, submit-vertices). No analysis logic in run.py.
- Diagnostics moved into the package: `module/diagnostics/{step5_compat,
  lowsp_diag,lowsp_spread_radius,bg_cost_spread}.py`, run via
  `python -m module.diagnostics.<name>`.
- Legacy ΛΛ-pair KEKCC shells (kekcc_intra/xconn/filter_job) moved into
  scripts/legacy/ with fixed references.
- status/monitor merged into one monitor: pipeline-overview logic →
  `module/pipeline_status.py` (run(loop)/main); `scripts/monitor.py --pipeline`
  is the overview (default when no live-job flags), live-job flags keep the
  old behavior; `scripts/status.py` is a deprecated wrapper.
- Deleted redundant submit_kekcc.sh (submit_kekcc.py covers bsub). Fixed
  leftover e07fullscan→module refs in kekcc_job.sh / analyze.sh.
- Added scripts/README.md mapping the slimmed surface.

### End state

scripts/ now: README.md, the active pipeline CLIs (delegated to by run.py),
monitor.py (single monitor), status.py (deprecated wrapper), the LSF shell
entry points (kekcc_job.sh, kekcc_vertex.sh, analyze.sh, run_pipeline_v6.sh),
and legacy/. Diagnostics live under module/diagnostics/.

### Verification

pytest -m "not slow" 52 passed at each phase; monitor.py --pipeline and the
status.py wrapper produce the overview; lowsp_spread_radius (now python -m)
reproduces the 2026-05-29 numbers. Commits: 7f55b9c (run.py), 502ba4d
(diagnostics+legacy .sh), ed9377f (status/monitor), 3179e5b (submit_kekcc.sh
delete + .sh refs + README).

---

## 2026-05-31 — Phase 3: CLI bodies into module/, review package, Codex sign-off

Follow-on to the 2026-05-30 scripts-surface cleanup. The thin-wrapper idea was
extended so that `scripts/*.py` carry no real logic: each is a ~7-line wrapper
that delegates into the `module/` package. Behaviour-preserving throughout.

### Why

After run.py became the dispatcher, the heavy bodies still lived in
`scripts/`, so the package was not actually the source of truth — the operation
surface and the logic were split across two trees. Moving the bodies into
`module/` makes `module/` self-contained and leaves `scripts/` as a pure entry
layer (wrappers + documented shell/recipe entries + legacy quarantine).

### Changes (by family, commit order)

- Family 1 (70733ff): clustering CLI bodies ->
  `module/clustering/_cli_find_vertices.py`, `_cli_merge_vertices.py`.
- Family 2a (5d47af3): merge_chunks body -> `module/merge/_cli_merge_chunks.py`.
- Family 2b (6fe5033): KEKCC submit bodies ->
  `module/analyze/_cli_submit_kekcc.py`, `_cli_submit_vertex_kekcc.py`.
- Family 3 (e22feb5): new `module/review` package; review CLI bodies ->
  `_cli_crop_vertices.py`, `_cli_vertex_map.py`, `_cli_review_crops.py`,
  `_cli_click_vertex.py`.
- Family 4 (d3e8fac): live-job monitor body -> `module/utils/job_monitor.py`;
  scripts/monitor.py reduced to a wrapper. (Pipeline-overview body already
  lived in `module/pipeline_status.py` from the 2026-05-30 status/monitor
  merge.)
- Codex review fixes (edd2dce): CLAUDE.md and AGENTS.md subpackage lists now
  include `module/review`, and document `module/pipeline_status.py` (pipeline
  overview) plus `module/utils/job_monitor.py` (live-job monitor body) as the
  monitor/status helpers. Fixed `scripts/status.py --help` so `-h/--help`
  prints the deprecation note + docstring and exits 0 instead of
  surprise-running the pipeline overview.

### End state

`scripts/` = README.md, the thin Python wrappers (find_vertices,
merge_vertices, merge_chunks, submit_kekcc, submit_vertex_kekcc, crop_vertices,
vertex_map, review_crops, click_vertex, monitor, status[deprecated]), the
documented shell/recipe entry points (analyze.sh, kekcc_job.sh,
kekcc_vertex.sh, run_pipeline_v6.sh), and legacy/. Everyday operation goes
through run.py; one monitor concept; heavy logic inside `module/`.

### Verification and Codex sign-off

pytest -m "not slow" -> 52 passed, 35 deselected (~49s) on a clean tree.
Codex gave the final structural sign-off on 2026-05-31 (after edd2dce),
confirming AGENTS.md/CLAUDE.md match the module/ structure and monitor-helper
split, that `scripts/status.py --help` no longer runs the overview, and that
run.py/monitor.py expose the intended surfaces. Codex did not rerun the full
pytest suite in that final check and accepted Claude's reported
`pytest -m "not slow"` result (52 passed, 35 deselected) without rerunning.
No remaining structural blocker. README gained a brief "Operation Surface"
note pointing to run.py while keeping existing scripts/*.py examples as
compatibility paths (fuller README rewrite deferred per Codex).
