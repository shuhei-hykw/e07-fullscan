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
