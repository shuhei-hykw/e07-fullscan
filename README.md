# module

Analysis toolkit for E07 nuclear emulsion full-scan data.

## Setup

Python is managed with pyenv; dependencies with requirements.txt.

```bash
pyenv install 3.14.6
pyenv local 3.14.6
pip install -r requirements.txt
```

Run everything from the repository root (`module` is imported from the
working directory; no package install is needed).

Dependencies: numpy, scipy, opencv-python, matplotlib, PyYAML, pandas,
pyarrow (+ flask for the web viewer, pytest/ruff for development)

## Package Structure

```
module/
├── reader.py        # SPNG format reader (SpngReader)
├── preprocess.py    # Steps 1–5: zpj → fog removal → Otsu → noise removal
├── run_info.py      # Run traceability (run_id, parquet metadata)
├── job_monitor.py   # Live-job monitor
├── pipeline_status.py  # Pipeline overview
├── pipeline/        # Hough track/vertex pipeline (steps 5+)
│   ├── finder.py          # find_tracks()
│   ├── track.py           # Track dataclass
│   ├── cluster.py         # cluster_tracks(), cluster_df()
│   ├── link.py            # link_tracks(), best_per_track()
│   ├── vertex.py          # find_vertices(), merge_vertex_slices()
│   ├── pairs.py           # find_vertex_pairs() (legacy ΛΛ)
│   ├── analyze_cli.py     # e07analyze / python -m module.pipeline
│   ├── merge_cli.py       # e07merge
│   ├── cli_find_vertices.py
│   ├── cli_merge_chunks.py
│   ├── cli_merge_vertices.py
│   ├── cli_crop_vertices.py
│   ├── cli_review_crops.py
│   ├── cli_vertex_map.py
│   ├── cli_click_vertex.py
│   ├── cli_submit_kekcc.py
│   ├── cli_submit_vertex_kekcc.py
│   └── diag_*.py          # Diagnostics (python -m module.pipeline.diag_X)
├── graphdet/        # Python port of the MATLAB graph detector
│   ├── geom.py            # norma/isaline*/mindistance*/L2lseg/lseg2L
│   ├── detectlseg.py      # detect_lseg_smallregion(), detect_lseg_view()
│   ├── polyfit.py         # pixellist_to_poly(), inflection_nodes()
│   ├── integrate.py       # integrate_smallregions()
│   ├── branch.py          # detect_branches(), branch_points()
│   ├── config.py          # DetectorConfig: every tunable distance
│   ├── downsample.py      # mabiki()
│   └── simeval.py         # scoring against the simulation truth
└── server/          # Web viewer (flask)
```

## Preprocessing Pipeline (Steps 1–5)

Steps 1–5 produce binary images passed to downstream graph analysis.

| # | Step | Key Parameters |
|---|---|---|
| 1 | Raw scan (SPNG read) | — |
| 2 | Z-Projection | zpj_half=4 (9 slices) |
| 3 | Fog Removal | fog_ksize=51 |
| 4 | Otsu Threshold | — |
| 5 | Noise Removal | noise_amin=2, noise_amax=100, noise_cmp=50 |

```python
from module.reader import SpngReader
from module.preprocess import zpj, preprocess

reader = SpngReader("path/to/tile.json")
binary = preprocess(zpj(reader))  # np.ndarray (H×W, uint8), ready for graph analysis
```

![Pipeline: steps 1–5](docs/pipeline.png)

Regenerate the figure:
```bash
python scripts/make_pipeline_fig.py [TILE_STEM] [--out docs/pipeline.png]
```

## SPNG Reader

```python
from module.reader import SpngReader, load_spng

reader = load_spng("path/to/scan.json")
len(reader)            # number of slices
reader.z_positions()   # Z coordinate per slice (float64 ndarray)
img   = reader.read(0)       # single slice (H×W uint8)
stack = reader.read_stack()  # all slices (N×H×W uint8)
for img in reader: ...       # iteration
```

The scanner metadata pixel scale (x=y=3 μm/px) is wrong.
Confirmed pixel scale from scan geometry: **0.29 μm/px** (FOV ≈ 594 μm).

## Operation Surface

```bash
python run.py --help              # list all commands
python run.py track ...           # Hough track analysis
python run.py vertices ...        # vertex finding
python run.py merge-tracks ...    # merge chunk parquets
python run.py merge-vertices ...  # cross-slice vertex merge
python run.py view                # web viewer
python run.py monitor ...         # live job monitor
python run.py status              # pipeline overview
python run.py submit-tracking     # KEKCC LSF batch submit
python run.py submit-vertices     # KEKCC vertex submit
python run.py matlab-export ...   # export 3-D hit list (.mat) for MATLAB
python run.py crops ...           # crop vertices for inspection
python run.py review              # web vertex review
python run.py map ...             # spatial vertex distribution map
python run.py click ...           # click ground-truth vertices
```

Each command delegates to `python -m module.<target>` with the same arguments.

## Batch Track Analysis (KEKCC)

```bash
# Submit 135 array jobs
python run.py submit-tracking     # reads config/kekcc.yaml

# Monitor progress
python run.py monitor --job-name e07full \
    --log-dir logs/kekcc --out-dir results --total 2025

# Merge chunks
python run.py merge-tracks \
    --input results --output results/merged.parquet
```

`config/kekcc.yaml` key settings:

```yaml
job:   {name: e07full, queue: s, n_cores: 2, mem_mb: 4000, n_jobs: 135}
data:  {input: /gpfs/.../IMAGE00_AREA00, output_dir: results, total_views: 2025}
analysis: {config: config/default.yaml, workers: 1}
```

## Vertex Finding

```bash
python run.py vertices \
    --input results/merged.parquet \
    --output results/vertices.parquet

python run.py merge-vertices \
    --input  results/vertices.parquet \
    --output results/vertices_merged.parquet \
    --crops  results/vertex_crops \
    --min-slices 3 --min-tracks 8
```

```python
import pandas as pd
from module.pipeline import find_vertices, merge_vertex_slices

df  = pd.read_parquet("results/merged.parquet")
vdf = find_vertices(df, min_tracks=3, max_ep=100.0,
                    min_intens=12.0, beam_angle_cut=15.0)
mdf = merge_vertex_slices(vdf, eps_xy=50.0, min_slices=3)
```

Key parameters: `min_tracks=3`, `max_impact=30 px`, `max_ep=150 px`,
`beam_angle_cut=15°` (removes ~22% beam-parallel tracks, reduces false
vertices by ~13%).

## MATLAB Graph-Detector Export

Bridge to the graph-theory event detector in `e07/matlab`
(`detect_tracks.m`). That detector's stage-1 input is a 3-D hit pixel list
`pl = {x, y, z, n, sheet, id}` (x, y in pixels, z = slice index); its
downstream stages only use `dspl = mabiki(pl, 3)`.

```bash
python run.py matlab-export tile.json -o tile_pl.mat
```

Unlike the Hough pipeline (which z-projects the stack into one 2-D image),
this binarizes each slice independently (fog removal -> Otsu -> noise removal)
and emits every foreground pixel as one 3-D hit. Coordinates are 1-based
(x = col + 1, y = row + 1, z = slice + 1) to match the MATLAB (1, 1, 1)
origin. The block-3 down-sampling (`mabiki`) is left to MATLAB; only the raw
`pl` is written, plus `variablenamespl`. `sheet`/`id` are 0 placeholders (no
track segmentation exists for real data), and `n` is the fog-removed
intensity.

Real tiles are dense (a 2048×2048×58 tile yields ~2×10⁷ hits), so MATLAB-side
`mabiki` down-sampling is essential before the graph stages.

## MATLAB Graph Detector, Ported (`module.graphdet`)

A Python port of the detector in `e07/matlab`, so the graph stages can
run on kekcc (no MATLAB is installed there) and so their constants can
be retuned against E07 data. Depends only on numpy and scipy.

All three stages are ported.

`detect_lseg_smallregion()` (from `detectlseg_smallregion.m`) turns one
128×128×80 sub-region of hits into 3-D line segments, and
`detect_lseg_view()` walks the 16×16 grid of a full view.
`integrate_smallregions()` then stitches those per-region segments into
whole tracks — chaining them end to end, re-fitting each chain against
the hits it owns (`pixellist_to_poly()`, from `pixellist2poly.m`), and
finally joining polylines across the gaps that chaining cannot bridge.
`detect_branches()` (from `detectbunki.m`) then groups tracks that meet:
a hit lying on one track's body and at another's end is evidence of a
branch, and the groups are the connected components of that relation.

```python
from module.graphdet import (
  branch_points, detect_branches, detect_lseg_view, integrate_smallregions)
segments, per_region = detect_lseg_view(hits)    # (2, 3, M) endpoints
tracks = integrate_smallregions(hits, segments)  # list of (K+1, 3)
grouped, group_id = detect_branches(tracks, hits)
vertices, multiplicity = branch_points(tracks, hits)
```

`branch_points()` is **not** in the MATLAB original, which returns
groups and never vertex coordinates. It derives them from the same
shared hits the grouping already found, because coordinates are what
the E07 analysis needs.

### Checking the port

`e07/matlab/work1.mat` stores a complete input/output chain — the 41,609
hits of simulation event 1, the 1,239 segments MATLAB's stage 1 produced
from them, and the 149 polylines its stage 2 produced from those — so
each stage can be checked in isolation with no MATLAB installation:

```bash
python scripts/check_lseg_reference.py        # stage 1
python scripts/check_polylines_reference.py   # stage 2, from ref segments
pytest -m slow tests/test_graphdet.py         # both, as tests
```

Stage 3 has no MATLAB reference to compare against — `detect_tracks.m`
never saves detectbunki's output. It is checked against the truth
instead (below), which is the more useful test anyway.

Stage 1 reproduces all 1,239 segments with a worst endpoint error of
2.5e-13 px, in 14 s for the whole view against roughly 9 h for the
MATLAB original (analysis-note.md, 2026-08-22).

Stage 2 returns the same 149 polylines with the same total track length
to 0.2%, and every polyline lies within 16 px of a reference one (half
of them bit-exact). It is **not** bit-reproducible, and cannot be: each
polyline's end vertex is by construction the projection of its own
outermost hit, so that hit sits at arc length exactly zero in the
"is this hit inside my extent?" test and falls on either side of it at
the 1e-13 level, differently under MATLAB's BLAS and NumPy's. The port
includes those hits deterministically (`_ELL_SLACK_PX`), which is what
the comparison means in exact arithmetic; taking MATLAB's literal `>= 0`
instead shrinks a fit by ~1 px per pass and can starve a short polyline
of hits entirely (analysis-note.md, 2026-09-07).

### How well it works

Agreement with MATLAB says the port is faithful, not that the detector
is any good. `simdata8.mat`'s `Summary` gives the truth: an endpoint
shared by two or more simulated tracks is a real branch point, 130 of
them across the 10 events.

```bash
python scripts/eval_branches.py --events 1-10
```

Distances are isotropic (one slice is ~10 px at the simulation's 3 µm
spacing), matching at 25 px:

| | value |
|---|---|
| efficiency | **96.2%** (125/130) |
| purity | **74.0%** (159/215) |

Efficiency is high; purity is the weak side — 215 vertices found for
130 real ones. Two caveats: 4 of the 125 matched truths collapse onto a
shared reconstructed vertex, so the resolution is worse than the
efficiency suggests, and a point where three track bodies cross passes
the `1 + 1 + 1 > 2` code test and is reported as a branch.

### Constants and calibration

Every distance the three stages measure against lives in
`config.DetectorConfig`, and every entry point takes a `cfg=`. The
defaults are the MATLAB values, so passing nothing reproduces the
reference run.

The file's organising idea is the split between a **transverse
tolerance** (`th_split`, `attach_max_dist`, ...) — a distance measured
across a track, i.e. its width plus measurement error — and a **length
scale** (`grow_margin`, `end_reach`, ...) — a distance measured along a
track or between neighbouring hits. Only the second has to grow when
the hits get sparser, and `DetectorConfig.for_spacing()` scales only
those.

That distinction was worth making. The MATLAB constants were tuned at
~3 px hit spacing; the E07 export used to sample at 30 px, and
re-thinning the same simulation to that spacing (`mabiki`, ported in
`downsample.py`) drops branch-point purity from 78.8% to 17.5%:

```bash
python scripts/scan_sampling.py --events 1-3 [--scale-constants]
```

| hit spacing | efficiency | purity |
|---|---|---|
| 3 px | 92.7% | 78.8% |
| **6 px** | 85.4% | **75.9%** |
| 10 px | 75.6% | 58.9% |
| 30 px | 53.7% | 17.5% |

Stages 1 and 2 survive the coarse grid — 98% of the track length is
still reconstructed, and all 14 true vertices still have a polyline
vertex within 25 px. Stage 3 does not, and no constant fixes it:
detectbunki decides a branch from hits shared within 1.5 px, and a
coarse grid is precisely what removes them. So the answer was to sample
finer, not to retune — `matlab_export._GRAPH_CELL_PX` is now 6 px.

`for_spacing()` rescales **only** the hit-spacing group. Scaling the
track-geometry gaps as well was measured to be worse at every usable
spacing (at 6 px, 90.2%/66.0% against 87.8%/**75.5%**; purity is the
weak side) and it makes stage 2 quadratic on real data by widening the
endpoint search box tenfold.

### On real E07 data

One full-scan tile, end to end, at 30 px (2026-09-08):

| step | result | time |
|---|---|---|
| export | 240,824 hits | 80 s |
| stage 1 | 44,360 segments | 2,449 s |
| stage 2 | 28,988 polylines | 163 s |
| stage 3 | 20,511 groups, 8,118 branch points | 10 s |

It runs, which took four exact optimisations to achieve (see the
2026-09-08 analysis-note entries) — before them stage 1 alone
extrapolated to 21 hours per view and stage 3 wanted a 7 GB dense
matrix.

At 30 px the output is not usable: the simulation yields 149 polylines
per view where real E07 yields 28,988, and 13 branch points where it
yields 8,118, which is what a simulated purity of 17.5% looks like on
real data. 6 px is the setting the simulation argues for (75.9%), and
two things made it affordable:

- `export_hits_grid(denoise_method="classifier")`, using the classifier
  already trained on the existing labels, cuts 6 px hits from 1,667,324
  to 784,522. (The `"threshold"` mode is looser than `"legacy"` **and**
  ten times slower — there is no reason to use it.)
- `_merge_overlapping` now answers "is any other segment claiming this
  hit" for every segment at once, taking a 3,013-hit sub-region from
  331.8 s to 39.0 s.

| | 30 px, legacy | **6 px, classifier** |
|---|---|---|
| hits per sub-region (median) | 972 | 3,024 |
| export | 80 s | 853 s |
| stage 1 | 2,449 s | ~2.77 h |
| simulated purity | 17.5% | **75.9%** |

~3 h/view in total, and stage 1 peaks at 0.3 GB, so it belongs on LSF
queue `h` one view per job. That end-to-end run has not been done yet.

`z_scale` is still the MATLAB `3.0 / 0.29`, which assumes 3 µm slices;
E07 is 1.5 µm/slice, and `config.E07_Z_SCALE` holds the right value.
The simulation cannot validate that switch, since 3.0 / 0.29 is correct
there.

## Batch Submission (KEKCC / LSF)

```bash
python -m module.pipeline.cli_submit_kekcc --array 1-20   # pilot first
python -m module.pipeline.cli_submit_kekcc --array 21-2025
python -m module.pipeline.cli_submit_vertex_kekcc \
    --chunk-dir results/fullscan_v7 --vertex-dir results/vertex_v7
```

`queue: auto` in `config/kekcc.yaml` picks the queue at submission
time. Which queue is best changes by the hour — on the evening of
2026-09-08 queue `h` had nothing pending, and by the next morning it
had 2,820 while `p` was empty — so a queue named in a config file is
stale before it is ever used. `module/pipeline/lsf_queue.py` asks
`bqueues` which queues this user may submit to, drops any whose CPU,
wall, memory or **task** limits cannot hold one job, and ranks the rest
by how many jobs could start immediately and then by backlog.

Two limits are invisible in the table form of `bqueues` and both
rejected a submission outright:

- Queue `p` has `TASKLIMIT 2 4 64` and refuses `-n 1` with "Too few
  tasks requested". Vertex finding is single-threaded, but asking for
  two slots is what makes `p` usable, and `p` runs 120 of our jobs at
  once against queue `a`'s 4.
- `MAX_JOB_ARRAY_SIZE` is 1000, so a 2,025-element array cannot be
  submitted. The submitters split it automatically.

**Always run a pilot first.** `--array 1-20` submits a real slice of
the same partition, so nothing is wasted, and it finishes in three
minutes. The 2026-09-09 pilot caught a job script calling a module that
had been renamed away in May, a vertex submitter asking for 8 GB on a
4 GB queue, and stale May error logs that read as failures. Each would
otherwise have failed 2,025 times.

Measured per job on a batch node (2026-09-09): tracks 125–134 s CPU and
1.2 GB, vertices ~20 s and 0.7 GB — both comfortably inside the 4 GB
cap that applies to every kekcc queue.

## Web Viewer

```bash
python -m module.server /path/to/scan_dir --port 8000
# SSH tunnel: ssh -L 8000:localhost:8000 user@login.kekcc.jp
```

| URL | Description |
|---|---|
| `/view/` | Image viewer — live pipeline preview, SPNG browsing |
| `/results/` | Results viewer — stored track images |
| `/viewer3d/` | 3D viewer — interactive track visualization |
| `/label/<tile>/<idx>` | Review one tile's candidates, longest first |
| `/label_mix` | Review across several tiles |
| `/label_uncertain` | Review where the classifier is least sure |
| `/label_disagree` | **Review where the classical classifier and the CNN disagree** |

### Reviewing segments

Each page shows one Hough candidate at a time — raw, fog-removed, and
fog-removed with the segment highlighted — and you answer true (real
track) or false (junk) with the arrow keys or the buttons. Decisions
land in `results/manual_labels/` and a session can be resumed.

`/label_disagree` is the one to use when both a classical classifier
and a CNN exist. A candidate they both call the same thing teaches
neither model anything; the informative clicks are where they differ,
and there are plenty — measured over 47,498 candidates on the four
labelled tiles at production parameters, the two reach **opposite
verdicts on 30%**, and 396 differ by more than 0.7 in probability.

It needs CNN probabilities, which are read from a file because torch
and OpenCV deadlock in one process. Regenerate them in the sibling ML
repo after changing the model:

```bash
cd ../e07-ml-binary-segmentation/src
python dump_segments.py --all-candidates --hough 35,30,40 \
  --out-dir ../data/segments_all
python score_candidates.py --checkpoint ../results/<run>.pt
```

The first queue request takes ~80 s while Hough and the features are
computed for each tile; everything after that is ~0.1 s, since none of
it depends on the decisions.

> **Label files are per Hough parameter set.** A decision is an index
> into the candidate list, so it only means anything alongside the
> parameters that produced that list. Review switched from
> thr=8/ml=10/mg=20 to the production 35/30/40 on 2026-07-23 while the
> existing 512 decisions were all recorded under the old values, so
> new decisions go to `..._z29__t35l30g40.json` rather than being
> merged into `..._z29.json` and silently repointing every old one at
> a different segment. Treat the two files as **different
> populations**, not one pooled count.

## Run Traceability

```python
from module.run_info import (
    make_run_id,            # "20260510_165200_abc1234"
    build_run_meta,         # {run_id, script, timestamp, python, params}
    save_run_json,          # write <stem>_run.json sidecar
    save_parquet_with_meta, # parquet + embedded run_meta
)
```

Every parquet output embeds `run_meta` in schema metadata.

## Tests

```bash
pytest            # fast tests only
pytest -m slow    # integration tests on confirmed events (specials_x20)
```

The slow suite reads `specials_x20`; it defaults to the KEKCC path, so on
other machines set `E07_SPECIALS_DIR` to a local copy, e.g.
`E07_SPECIALS_DIR=$PWD/specials_x20 pytest -m slow`.

## Analysis Notes

Physics findings and parameter decisions: [analysis-note.md](analysis-note.md)
(development diary in Japanese, newest entry first; replaced ANALYSIS.md /
ANALYSIS_ja.md on 2026-07-11).

## Legacy ΛΛ Pair Scripts

Scripts for the historical ΛΛ pair catalog are in `scripts/legacy/`.
They are not part of the current pipeline (superseded 2026-05-14).
KISO cross-view result: P=(354,1204) n=11 ↔ S=(1888,716) n=5, d=152 μm.
