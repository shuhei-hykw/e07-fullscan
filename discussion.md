# Discussion Log

Shared coordination notes for Codex and Claude Code while both agents are
working in this repository.


**Older entries**: everything before 2026-07-11 moved to `discussion_archive_2026H1.md` on 2026-07-27 (content unmodified).

## 2026-07-11 13:30 JST — Claude: intent — commit & push MATLAB export prototype

User approved committing the 2026-06-23 prototype. Action: append 2026-07-11
ToDo-review diary entries to ANALYSIS.md / ANALYSIS_ja.md, then commit the
whole set (`module/matlab_export.py`, `run.py`, README.md, ANALYSIS.md,
ANALYSIS_ja.md, discussion.md, discussion_ja.md) as one feature commit on
`main` and push to `origin/main`. No jobs launched, no data outputs; the
prototype `.mat` stays outside the repo. Owned files unchanged from the
2026-06-23 entry. A Notion image-pre-processing DB row for 2026-07-11 will be
added after the push.

## 2026-07-11 13:58 JST — Claude (macOS): done — repo verified on macbook, two portability fixes

Cloned repo now lives on the macbook (`~/work/e07/e07-fullscan`, iCloud-backed;
same tree as kekcc HEAD `baa81a2`). Set up `.venv` (Python 3.14, OpenCV 5.0)
and verified the full test suite: 52 non-slow + 35 slow (with
`E07_SPECIALS_DIR` pointing at the local `../specials_x20` copy) — 87/87 pass.
Two portability fixes were required, uncommitted for now:

- `pyproject.toml`: `build-backend` was the non-existent
  `setuptools.backends.legacy:build`; fixed to `setuptools.build_meta`
  (pip editable install failed otherwise).
- `module/pipeline/finder.py`: OpenCV 5 returns `HoughLinesP` as `(N, 4)`
  instead of `(N, 1, 4)`; replaced `lines[:, 0]` with `lines.reshape(-1, 4)`
  (works on both OpenCV 4 and 5).

Owned files: `pyproject.toml`, `module/pipeline/finder.py`. No jobs launched,
no data outputs. Note: `fullscan-image` symlink still points at the kekcc
absolute path `/group/had/sks/E07/tohoku/fullscan`; an sshfs mount at
`~/mnt/kek_e07` is prepared (FUSE-T) but not yet mounted.

## 2026-07-11 14:09 JST — Claude (macOS): done — pyenv + requirements.txt migration, agent files untracked

Per user request:

- `AGENTS.md` / `CLAUDE.md` removed from git tracking (`git rm --cached`) and
  added to `.gitignore` (files kept locally). `.python-version` ignored too.
- New `requirements.txt` (core + flask + pytest/ruff). `pyproject.toml`
  stripped to tool config only (pytest markers, ruff); the `[project]`
  packaging metadata and `e07analyze`/`e07merge`/`e07view` console scripts
  are gone — grep confirmed nothing outside old diary entries used them, and
  `run.py` delegates to `python -m module.<target>`.
- Python now managed by pyenv: 3.14.6 built and set via `pyenv local`
  (`.python-version`, untracked). Old `.venv` removed. `module` imports from
  the repo root, so no editable install is needed.
- README Setup / Tests sections updated (pyenv flow, `E07_SPECIALS_DIR` note).
- Verification: 52/52 non-slow tests pass on the pyenv interpreter; slow
  suite running, result to be appended.

Owned files: `.gitignore`, `requirements.txt`, `pyproject.toml`, `README.md`.

## 2026-07-11 14:20 JST — Claude (macOS): done — diary unified into analysis-note.md, Notion retired

Per user decision:

- Notes are now a single file `analysis-note.md` (Japanese), replacing
  `ANALYSIS.md` / `ANALYSIS_ja.md` (both `git rm`ed; git detected the rename
  from ANALYSIS_ja.md, so history follows). All 43 dated entries migrated.
- Entries are reverse-chronological (newest first) with times:
  `## YYYY-MM-DD HH:MM JST — <title>` inserted right below the
  `## 開発ログ（最新が上）` heading. Pre-existing date-only headers were left
  untouched except today's three, whose times were recovered from commit
  timestamps and work logs.
- リファレンス and 未解決課題 sections stay at the top of the file.
- Notion (image-pre-processing DB) is retired; the corresponding CLAUDE.md /
  AGENTS.md rules were rewritten, and README now points to analysis-note.md.
- Also: slow suite re-verified on the pyenv interpreter — 35/35 pass
  (~8.5 min), completing the pyenv migration check (52 + 35 = 87/87).

Owned files: `analysis-note.md`, `README.md`, `CLAUDE.md`, `AGENTS.md`.
Note for Codex: ANALYSIS.md / ANALYSIS_ja.md no longer exist; read
`analysis-note.md` instead when reconstructing working memory.

## 2026-07-11 15:29 JST — Claude (macOS): done — first real-data MATLAB test: detectlseg does not scale

Ran the graph detector's stage 2 on real data for the first time
(macbook, MATLAB R2026a, KISO specials tile). Export (12.36M hits) and
mabiki(pl,3) (7.7 s -> 2.46M pts) are fine; detectlseg_smallregion is the
wall: ~N² per region, 2,991 pts -> 291 s, 117/256 regions exceed 10k pts,
extrapolated ~392 h per tile. Run aborted after 1 h (13/256 regions).
Multiplicity cuts don't help (real-data 3×3 blocks are saturated, nn=9 is
the largest bin). Estimated levers: n≥40+mabiki3 -> ~5.7 h,
n≥40+mabiki6 -> ~1.8 h, but intensity cuts keep only ~10% of hits and
clash with the efficiency-first policy. Full numbers in analysis-note.md
(2026-07-11 15:29 entry). Next-step options listed there; awaiting user
direction. Owned files: results/matlab/* (gitignored), analysis-note.md.

## 2026-07-11 18:29 JST — Claude (macOS): done — centroid-mode MATLAB export makes detectlseg tractable (KISO full run)

Per user direction (don't change MATLAB .m files; reconsider the front-end
preprocessing instead). Root cause of test #1's ~392 h estimate: raw-pixel
export emitted one hit per binary pixel, so one grain blob (tens of px)
became tens of duplicate hits -- denser than what "1 hit = 1 grain" means to
detect_tracks.m.

Added `export_hits_centroid()` to `module/matlab_export.py` (now the CLI
default; `--mode pixel` keeps the old behaviour for comparison): one 3-D hit
per per-slice connected-component centroid instead of one per raw pixel.
No hits are dropped by brightness (unlike an intensity cut), so this doesn't
trade away efficiency-first the way earlier cut estimates would have.

Result on KISO: 12.36M -> 101k hits (122x), max-region points 26,962 -> 838
(32x). Ran detectlseg_smallregion over the full 256-region grid for the
first time to completion: 9,067.5 s (2.52 h), 24,799 segments, matching the
pre-run N^3 extrapolation (2.48 h) closely. The known-vertex region (137,
vx=1096/vy=1028/z_slice=10 per tests/specials_gt.json) has 113 segments
within 80px/±8 slices of it -- plausible track density, not empty or noise.
detectbunki (branch-point / vertex reconstruction) not run yet -- this only
confirms detectlseg tractability + plausible segment density, not that the
known ΛΛ vertex is recoverable end-to-end.

Full numbers and next-step options in analysis-note.md (2026-07-11 18:29
entry). Fast test suite re-verified (52/52) after the matlab_export.py
change. Owned files: module/matlab_export.py, analysis-note.md,
results/matlab/* (gitignored, not committed). No MATLAB (.m) files touched.

## 2026-07-11 20:14 JST — Claude (macOS): done — intensity-weighted centroids + web-viewer visualization of the raw-to-MATLAB-hits pipeline

Two follow-ups to the centroid-mode export (commit 9239c11):

1. `module/matlab_export.py`: added `weighted_centroids(binary, intensity)`,
   replacing the shape-only `cv2.moments(cnt)` with an intensity-weighted
   centroid (masks each blob's bounding box against the fog-removed image
   before `cv2.moments`). Verified on KISO slice 10: mean shift from the
   geometric centroid 0.49px, max 14.98px (area-3075 blob) -- larger/
   irregular grain clusters shift the most, as expected.
   `export_hits_centroid()` now uses this; hit count and export time
   unchanged (101,479 hits, ~5s).
2. `module/server/app.py`: added a "Grain Centroids (MATLAB)" step to the
   `/view/` pipeline sidebar (between Noise Removal and Hough Lines).
   Restructured `_process()` to keep the fog-removed grayscale around after
   thresholding (previously overwritten), so centroids render as an
   overlay (yellow ring = blob radius, red dot = weighted centroid) on top
   of the actual grayscale rather than the binary silhouette.

Visual check on the KISO known vertex (vx=1096, vy=1028, z_slice=10, per
tests/specials_gt.json): fetched the four pipeline stages (raw / fog /
binary / centroid overlay) from the running local viewer
(`python -m module.server specials_x20 --port 8123`), cropped to a
400x400px window around the vertex. Several track-like lines visibly
converge near the crop centre in the fog-removed image, matching the known
vertex; centroids in the overlay track along those same lines rather than
scattering randomly -- density reduction preserved real structure. 4-panel
comparison published as an artifact:
https://claude.ai/code/artifact/8f9a90a2-7186-41e2-992c-3e80fd078241

Fast suite re-verified (52/52). Owned files: module/matlab_export.py,
module/server/app.py, analysis-note.md. Local viewer left running on
:8123 for interactive follow-up.

## 2026-07-11 21:03 JST — Claude (macOS): done — clarified panel 04, switched centroid overlay to real blob outlines

User asked how to read panel 04 and whether MATLAB was already doing the
clustering. Answer: it isn't -- `mabiki` is deliberately bypassed in the
centroid-mode test path and `detectlseg_smallregion` (the actual line/
track clustering) hasn't been run in this session; the grain-level
reduction shown in panel 04 is entirely `module/matlab_export.py`'s
Python-side `weighted_centroids()`, pre-MATLAB.

Root cause of the visual confusion: the overlay drew a circle sized by
sqrt(area) per blob, and near the vertex several tracks' grains merge
into large connected components (area > 3000px), which read as
hand-drawn cluster boundaries rather than "one point, size-annotated".

Fix: `weighted_centroids()` now also returns the raw contour
((cx, cy, area, contour) 4-tuples); `module/server/app.py`'s `cent` step
draws the actual blob outline (red) + a cross at the weighted centroid
(yellow) instead of a size-proxy circle. One outline <-> one cross is now
visually unambiguous, and outlines elongated along track directions are
now visible. Re-verified at the KISO known vertex; artifact updated in
place (same URL):
https://claude.ai/code/artifact/8f9a90a2-7186-41e2-992c-3e80fd078241

Fast suite re-verified (52/52). Owned files: module/matlab_export.py,
module/server/app.py, analysis-note.md.

## 2026-07-11 21:19 JST — Claude (macOS): done -- connected-component mode had a critical bug (long tracks collapse to 1 point); replaced with fixed-grid binning

User asked a chain of questions that led to discovering a real defect:
"don't we need clustering", "is passing all raw pixels bad", "is passing
the binary image (pre-clustering) as-is also bad".

Found: KISO has a connected component with bbox extent 882px (area only
4845px -- clearly one long, continuously-connected track). The previous
`weighted_centroids()` (connected-component-based) collapsed it to ONE
point, destroying all line/vertex information. 1,123/101,479 hits
(~1.1%) came from blobs with extent >100px -- not a rare edge case.
Visually confirmed via the web viewer (one long line, one cross).

Re-confirmed raw-pixel mode is intractable via two independent
extrapolations from real timing data: a robust 157-point log-log fit
(k=2.887) gives ~15,000 days for the full tile; a self-consistent fit
from raw-pixel-mode's own 2 real data points (k=2.11) gives ~635 days.
Orders of magnitude apart, but both obviously catastrophic -- passing
either raw pixels or the binary mask as-is (same thing: export_hits /
pixel mode) is a dead end regardless of which fit is trusted.

Replaced connected-component clustering with fixed-grid binning
(`weighted_grid_hits`, `export_hits_grid` in `module/matlab_export.py`):
no `cv2.findContours`, no shape/connectivity grouping at all -- pixels
are assigned to a fixed 30px x 30px cell purely by position, one
intensity-weighted hit per occupied cell. A cell-size sweep (10/15/20/25/
30px) with detectlseg runtime estimated from a robust power-law fit
picked 30px: 130,364 hits (vs 101,479 for the old connected-component
mode), max region 1,111 pts, est. ~6h/tile (close to the proven 2.52h).
Re-exported KISO and confirmed the former 882px single-point track now
yields 468 points. Web viewer's "Grain Centroids" overlay now draws faint
grid lines + a cross per grid hit (no more blob outlines -- there's no
blob concept anymore).

Launching a real full-256-region detectlseg run now to verify the ~6h
estimate empirically (background). Fast suite re-verified (52/52).
Owned files: module/matlab_export.py, module/server/app.py,
analysis-note.md, results/matlab/* (gitignored).

## 2026-07-12 02:53 JST — Claude (macOS): done -- fixed-grid mode's full-tile detectlseg run confirms the ~6h estimate

Follow-up to the previous entry (connected-component -> fixed-grid switch).
Ran detectlseg_smallregion over all 256 regions on the grid-mode KISO
export (130,364 hits): 19,802.2s (5.50h), 30,179 segments -- matches the
pre-run power-law estimate (~6.01h) closely, validating the extrapolation
approach used throughout this investigation. Slower than the connected-
component mode's proven 2.52h, but that's the accepted cost of fixing the
long-track-collapse defect.

Known-vertex region check (KISO vx=1096/vy=1028/z_slice=10): 81 segments
within 80px/±8 slices (vs 113 under the old connected-component mode) --
comparable density, structure preserved.

Status: MATLAB (.m) files remain untouched throughout this whole
investigation; all fixes were in module/matlab_export.py (the front-end).
Went from an estimated 392h (raw pixel) to a real 5.5h/tile, while also
fixing a correctness bug that would have silently destroyed long-track
information. Next open questions: scaling to all 2025 tiles (5.5h/tile is
not practical without parallelism/more compute), and running detectbunki
to see if the known vertex is actually reconstructed end-to-end.

Fast suite still 52/52 (no export-side changes this round, MATLAB-only
run). Owned files: analysis-note.md, results/matlab/* (gitignored).

## 2026-07-12 15:25 JST — Claude (macOS): done -- hybrid (connected-component + local grid) point reduction, visually confirmed fix

Context clarified by user: Python preprocessing -> MATLAB candidate
vertex selection -> scanner (human) review -> results fed back as
teacher/ground-truth data. MATLAB stays unmodified; only the front-end
preprocessing is in scope.

Read detectlseg_smallregion.m in full to explain its cost to the user:
stage 1 builds a full pairwise-distance matrix (pdist) then a min-spanning
tree, cutting edges until each component is line-like; stage 2 grows/
merges/refines segments via SVD-fit + nearest-point search, iterated to
convergence. The pdist call is O(N^2) pairs -- dominant cost, consistent
with the ~N^2.9 empirical fit (plus the iterative loops adding more O(N^2)
passes).

User proposed Hough-based resampling (detect track direction first, keep
points along it). Prototyped per-slice cv2.HoughLinesP: default (z-
projection-tuned) params only cover 24-30% of foreground pixels per
slice; relaxed params reach 77-83% but produce 5000+ overlapping segments
per slice needing dedup/merge logic similar to the existing
cluster_tracks/link_tracks -- too much added complexity for now.

Went with a simpler fix instead: weighted_grid_hits() now groups by
connected component first (basic connectivity, not shape/line
clustering) via cv2.connectedComponentsWithStats, then applies the fixed
cell grid *within* each component only when it exceeds cell size. Cost is
nearly identical to the plain grid (KISO: 133,183 hits vs 130,364; max
region 1,201 vs 1,111). Visually confirmed the fix: found 671 close-but-
disconnected component pairs in one slice; a 6-7x zoomed comparison shows
the old plain-grid mode placing points in empty space between two
distinct track structures, while the hybrid mode's points land on real
structure every time.

Fast suite 52/52. KISO re-exported (133,183 hits, 4.3s). Full-tile
detectlseg re-validation (~5.5-6h) NOT yet re-run given near-identical
density to the already-validated plain grid -- deferred pending user
decision on whether to spend the compute. Owned files:
module/matlab_export.py, analysis-note.md, results/matlab/* (gitignored).

## 2026-07-12 17:25 JST — Claude (macOS): done -- skeleton-based centerline extraction implemented, visually and quantitatively verified

Follow-up to the integrate_smallregions crash and track-width findings.
Resolved the "isn't this duplicating MATLAB's track detection" concern by
scoping this as image-level shape cleanup (same category as fog-removal/
Otsu/noise-removal), not track/vertex identification -- MATLAB keeps that
job.

Added scikit-image (skimage.morphology.skeletonize) to requirements.txt.
weighted_grid_hits() now thins any connected component larger than the
cell size to a 1-px medial-axis skeleton before cell sampling -- hit
*position* comes from the skeleton's weighted centroid, hit *n* (density
proxy) still comes from the original blob's per-cell pixel count. Total
hit count is unchanged (133,183 -- same cells, only position moved).

Quantified on the known 882px long track (properly isolated to just that
one connected component -- a bounding-box filter pulls in unrelated
points and gives nonsense numbers, learned that the hard way twice now):
local (40px window) perpendicular half-width dropped from mean-of-max
8.12px / median-of-max 6.63px / mean-of-mean 2.24px to 2.70 / 2.51 / 1.56
respectively -- a ~2.6-3x reduction, closer to but not fully under
detectlseg_smallregion's TH=1.5-2px tolerance (grid-cell chunking itself
still contributes some residual scatter).

Built a two-panel visualization (full-length overview + 6x zoomed detail)
showing the original wide blob outline (blue), skeleton (cyan), and final
exported hit points (yellow) all overlaid -- makes the width collapse
directly visible. Appended to the existing artifact (same URL):
https://claude.ai/code/artifact/8f9a90a2-7186-41e2-992c-3e80fd078241

NOT yet re-tested: whether this actually stops integrate_smallregions
from crashing (would need to re-run the 5x5-region local test, ~86 min).

Fast suite 52/52. KISO re-exported (133,183 hits, 5.3s). Owned files:
module/matlab_export.py, requirements.txt, analysis-note.md,
results/matlab/* (gitignored).

## 2026-07-12 18:44 JST — Claude (macOS): in-progress -- noise-reduction investigation (3 parallel tracks), analysis-note.md caught up

Caught up analysis-note.md with everything since the last commit (skeleton
implementation): confirmed skipping along-track decimation is not viable
(505 days est. for full-skeleton, no-chunking mode), retracted the pdist
MATLAB speedup (profiling showed subfunc1/pdist is only 0.4% of runtime;
no MATLAB files were ever modified), confirmed integrate_smallregions
crashes on real fragmented data (root cause: track width 3-4x over
detectlseg's TH tolerance), and logged the skeleton fix's quantified
improvement (~2.6-3x width reduction).

New this session: tested 3 classical noise-discrimination signals for the
"66% of points are small isolated components" question --
elongation (failed, no area correlation) and isolation-distance (failed,
median 21px to nearest structure regardless of real/noise) both gave no
separation. Hough-line-alignment succeeded: components >=3px from any
detected Hough line have median area 20 vs 114 for aligned ones. Raw
threshold removes 28.6% of the point budget, but a vertex-region spot
check found it would also drop non-trivial blobs (area 114-173) near the
one region we care most about -- combining with an area<30 floor is safer
(18.8% reduction) and a visual check confirms it protects real
track-aligned blobs the pure alignment filter would have dropped.

Found RIKEN researcher Kasagi's (independent, not shareable) code
`binary_segmentation` locally -- a segmentation_models_pytorch U-Net
binary segmentation model (grayscale in, track mask out) trained via
MC+GAN-generated data, i.e., a learned replacement for our classical
fog/Otsu/noise-removal step. No weights available (independent research).

User wants 3 tracks pursued in parallel: (1) validate/finalize the
conservative Hough-alignment noise filter, (2) prototype synthetic
training data (real background crops + simplified procedural track
geometry calibrated from specials_x20 statistics + measured grain
texture, skipping full Geant4+GAN), (3) investigate the public "UCS"
(SAM-based universal curvilinear structure segmentation) model for
transfer-learning feasibility -- delegated to a background agent
(GitHub: kylechuuuuu/UCS), awaiting its report.

TODO next: finish (1) and (2); read back the UCS agent's findings for (3)
when it completes. Owned files: analysis-note.md, results/matlab/*
(gitignored, various exploratory scripts), ~/work/e07/binary_segmentation
(external repo, read-only reference, not part of e07-fullscan).

## 2026-07-12 18:49 JST — Claude (macOS): done -- round 1 of 3 parallel tracks complete (Hough filter validated visually, synthetic-data prototype working, UCS ruled out / micro-sam found)

(1) Visual check of the conservative Hough-alignment filter (unaligned AND
area<30px) at the known vertex confirms it protects real signal that a
pure alignment-only filter would drop (several orange-marked
"unaligned but area>=30" components sit directly on visible track
lines). Conservative (18.8% budget cut) recommended over aggressive
(28.6%) pending a real detectlseg re-run.

(2) Copy-paste synthetic-track prototype works: real grain patches
(harvested from isolated small blobs) pasted along generated line paths
onto a real background, converging at a synthetic vertex -- visually
plausible, sidesteps GAN domain transfer entirely since every pixel is
real. Caveats logged: grain spacing (8px) is a rough estimate not
rigorously calibrated, tracks are straight (no curvature/scattering
modeled), background may contain real unlabeled tracks (noisy labels
risk).

(3) Background agent completed UCS investigation: NOT recommended (no
released fine-tuned weights -- an unanswered 7-month-old HuggingFace
request confirms this, no LICENSE file, hardcoded personal-server
checkpoint paths). Found a much stronger alternative: micro-sam
(computational-cell-analytics/micro-sam, Nature Methods 2024) -- SAM for
microscopy specifically, published weights + small-dataset fine-tuning
tutorials. Noted vesselFM (3D vessels, CVPR25, non-commercial license)
as a secondary reference.

Artifact updated in place with two new panels (filter vertex check,
synthetic-track comparison) and a status note:
https://claude.ai/code/artifact/8f9a90a2-7186-41e2-992c-3e80fd078241

TODO next: (1) real detectlseg re-run with the conservative filter
applied -- primary interest is whether it reduces segment count M (the
true bottleneck per the earlier profiling), not just point count N; (2)
calibrate grain spacing/background selection for synthetic data; (3)
investigate micro-sam's actual setup and fine-tuning feasibility on
emulsion images. Owned files: analysis-note.md, results/matlab/*
(gitignored).

## 2026-07-12 19:06 JST — Claude (macOS): in-progress -- Hough noise filter shipped to module code, real MATLAB validation running, synthetic data calibrated, micro-sam ruled out

module/matlab_export.py: remove_unaligned_noise() implemented and wired
into export_hits_grid() (denoise=True default, --no-denoise CLI flag).
KISO re-exported: 108,671 hits (was 133,183, -18.4%, matches the earlier
sweep). Fast suite 52/52.

Re-launched the previously-crashed 5x5 local region test
(test_detectbunki_local.m) against the denoised export, running in
background (~86min est., same as the prior run). First 2/25 regions
show a MUCH bigger runtime win than the point-count reduction predicts:
row7/col7 went 930pts/232segs/165.9s -> 732pts/175segs/68.1s (-21% pts,
-25% segs, -59% time). Consistent with the profiling finding that cost
scales with segment count M, not point count N -- suggests noise removal
disproportionately cuts M. Awaiting full completion to see if
integrate_smallregions still crashes.

Synthetic-track prototype: measured real grain spacing via intensity-peak
detection along the reference 882px track (find_peaks on the fog-removed
intensity profile) -- median 9.00px, mean 9.49px over 110 peaks, closely
matching the earlier placeholder (8.0px). Adopted 9.0px and added slight
per-grain angular drift (curvature=1.5deg, simulating gentle multiple
scattering) for a less mechanically-straight look.

Background agent completed micro-sam investigation: also NOT
recommended, but for a different reason than UCS -- weights ARE publicly
available (Zenodo, MIT license, confirmed MPS support for Apple Silicon)
but the task design is a fundamental mismatch: trained for discrete
object instance segmentation (cells/nuclei/organelles: LIVECell,
TissueNet, DeepBacs), not dense binary segmentation of connected
curvilinear structures. Its AIS decoder could technically be repurposed
for a dense foreground mask but has no track record for line-like
structures and isn't worth SAM's compute cost for that. Agent's
converged recommendation across both UCS and micro-sam investigations:
skip large foundation models, train a small U-Net (via
segmentation-models-pytorch, the genuine public library Kasagi's fork
was built on, not RIKEN's private fork) from an ImageNet-pretrained
encoder on our own data -- this merges naturally with track (2)'s
synthetic-data work.

TODO next: finish the denoised local MATLAB test; scale up synthetic
data generation (hundreds-thousands of images); prototype a
segmentation-models-pytorch U-Net training run. Owned files:
module/matlab_export.py, analysis-note.md, results/matlab/* (gitignored).

## 2026-07-12 19:57 JST — Claude (macOS): done -- denoised local test complete: detectlseg much faster, integrate_smallregions still crashes identically

Full 25-region local test with the denoised export completed.
detectlseg_smallregion: 3240.6s / 4840 segments, vs the earlier
skeleton-only run's 5153.3s / 5768 segments -- time -37.1%, segments
-16.1%. Confirms the profiling-derived hypothesis (cost driven by
segment count M more than point count N) directionally: noise removal
cut runtime disproportionately more than it cut point/segment count.

BUT integrate_smallregions crashed with the exact same error as before
(pixellist2poly>subfunc2 line 136, indexing into an empty point list) --
identical stack trace, identical root cause. Our hypothesis that
front-end density/quality improvements would indirectly fix this crash
was WRONG: it's very likely a genuine, reproducible logic bug in
resamplingpoly/pixellist2poly (can construct a polyline candidate with
no matching real hit points) that recurs regardless of how clean the
input is, as long as fragmentation of any kind exists -- which any real
dense track structure will always produce to some degree.

This is a decision point: front-end (Python-only) fixes have hit their
practical ceiling for this specific crash. Options to bring to the user:
(a) a minimal defensive guard in pixellist2poly itself (MATLAB-side,
narrowly scoped to the empty-input edge case, not touching the
algorithm's normal-case behavior), (b) skip integrate_smallregions/
detectbunki for now and treat detectlseg_smallregion's line-segment
output as the deliverable for scanner review, (c) something else --
awaiting user direction.

Owned files: analysis-note.md, results/matlab/* (gitignored).

## 2026-07-12 20:57 JST — Claude (macOS): in-progress -- applied a minimal MATLAB fix (user-approved), re-running validation

User chose option 1 (minimal defensive guard) from the previous
decision point. Investigation while implementing revealed the fix
location needed to be different from what I originally proposed:

- pixellist2poly() has exactly one caller (grep-confirmed): resamplingpoly
  inside integrate_smallregions.m.
- My first attempt (early-return zeros(0,Dim) inside pixellist2poly for
  empty input) was insufficient: the caller unconditionally does
  `lseg(:,:,i) = polylines{i}([1 end],:)` at integrate_smallregions.m
  lines 107-110, BEFORE any length==0 check -- an empty polylines{i}
  would just move the crash there. Reverted this attempt (pixellist2poly.m
  restored byte-identical to the pre-edit backup, diff-verified).
- Actual fix: guard in resamplingpoly itself, right before the
  pixellist2poly call -- if x1 (matching hit points) is empty, skip the
  call, keep polylines{i}'s existing coordinate data untouched (safe for
  the unconditional downstream indexing), and just set lpoly2(i)=0. This
  is not a new convention: integrate_smallregions.m already has
  "if lpoly(i)==0 % skip zero-length lines, continue" at line 118 --
  the original code already anticipated this outcome, pixellist2poly just
  never produced it gracefully for the empty-input case.

Both edited files (~/work/e07/matlab, not under git) backed up with
.orig-20260712 suffix before editing. Verified with MATLAB checkcode
(pre-existing style warnings only, no parse errors).

Re-running the same 5x5 local region test in the background (~50-90min,
detectlseg has to redo since MATLAB has no persistent state across
-batch invocations). Added a checkpoint save (lseg + x_local to .mat)
partway through the test script so future re-tests of just the
downstream steps won't need to redo detectlseg.

Owned files: analysis-note.md, results/matlab/test_detectbunki_local.m,
~/work/e07/matlab/{pixellist2poly.m,integrate_smallregions.m} (external,
not part of e07-fullscan git repo).

## 2026-07-12 21:52 JST — Claude (macOS): done -- MATLAB fix worked. First-ever full pipeline completion (detectlseg -> integrate_smallregions -> detectbunki), promising branch candidates found near the known vertex

Re-ran the same local 5x5 region test with the resamplingpoly guard
applied. integrate_smallregions completed WITHOUT crashing (8.0s, 2381
polylines) -- first time this whole investigation has gotten past this
step on real data. detectbunki also completed (2.0s, 1815 branch
groups, 107 with >=3 converging polylines).

Branch groups within 80px of the known KISO vertex (vx=1096/vy=1028/
z_slice=10): group 1 (21 polylines, 34.8px), group 5 (10 polylines,
14.5px), group 12 (7 polylines, 29.6px), group 31 (5 polylines, 20.8px),
group 41 (4 polylines, 44.0px), group 98 (3 polylines, 14.5px). Group 1
and 5 are well within specials_gt.json's own click tolerance
(+-50-100px) and the test suite's matching tolerance (+-200px).

Caveats logged (avoiding overclaiming): single local region test only,
tile-wide reproducibility unverified; haven't visually confirmed group
1/5's actual polylines correspond to KISO's real 3 known tracks; the
">=3 polylines" display filter is my own choice, not full visibility
into all 1815 groups.

TODO next: visualize group 1/5's actual polyline geometry against the
known tracks; if it checks out, scale up to a larger/full-tile
reproducibility test. Owned files: analysis-note.md,
results/matlab/test_detectbunki_local.m (checkpoint save added),
~/work/e07/matlab/{pixellist2poly.m,integrate_smallregions.m} (external).

## 2026-07-12 21:58 JST — Claude (macOS): done -- visualized group 1/5 polylines: a busy tangle, not a clean convergence, appropriate as a scanner-review candidate

Fast re-run from checkpoint (export_vertex_groups.m, skips detectlseg,
<10s) extracted group 1/5's actual polyline coordinates and overlaid
them on the fog-removed image around the known vertex. Honest read:
not a textbook clean 3-track convergence -- group 1 (orange) is a busy
tangle of many short crossing polylines; group 5 (yellow) radiates from
near the vertex in multiple directions, loosely consistent with real
tracks but not simple either.

Framed this appropriately given the user's own stated design (MATLAB
output -> candidates for scanner review, not full automatic
resolution): this messy-but-converging structure is a reasonable
candidate for that human-review step, not a failure. Added to the
artifact (same URL).

Current status: single local-region, single-event success; not yet
reproduced tile-wide or on other specials_x20 events. Natural next step:
re-run on other known events (IBUKI, IRRAWADY, NAGARA -- all n_clicks>=2)
or a wider region, to check generality before trusting this as a
repeatable result.

## 2026-07-14 01:05 JST — Claude (macOS): done -- fixed stale/low-quality
images in both published summary artifacts (panel 04 + 2 others)

User feedback: panel 04 (grid-hits visualization) looked "completely
no good" while the skeleton (cyan) images looked best. Root cause was
twofold: (1) `kiso_cent_vertex_crop.datauri` was generated 2026-07-12
14:37, before both the skeletonize commit (`cca63da`, ~17:25) and the
Hough-alignment denoise commit (`da3d5a8`, ~19:06) -- the artifact had
been showing an already-superseded plain-grid render this whole time;
(2) the existing cv2.drawMarker-based rendering lacks anti-aliasing
vs. the matplotlib-based skeleton figures the user praised.

Fix: wrote `results/matlab/regen_panels.py` (gitignored, under
results/) to regenerate 3 images from the CURRENT pipeline
(`weighted_grid_hits` + `remove_unaligned_noise`, cell=30px) using
matplotlib with the same cyan (`#5fd0c4`) accent as the skeleton
figures: panel 04 (`kiso_cent_vertex_crop`), the noise-filter check
(`filter_vertex_vis`), and the detectbunki branch-group overlay
(`vertex_groups_overlay`, from `vertex_groups_export.mat`). Republished
both artifacts (`kiso_vertex_pipeline_qa`, `e07_summary.html`) at their
existing URLs -- no pipeline code changed, only stale/low-quality
visualization assets.

Lesson: reused intermediate datauri images across artifact updates
without checking timestamps against the commits that changed the
underlying pipeline -- going forward, any time a visualization is
replaced, audit every artifact panel that reuses the same asset name
for staleness. Owned files this session: analysis-note.md,
results/matlab/regen_panels.py (new, gitignored),
scratchpad build_gallery.py / build_summary.py (regenerated HTML only,
no logic changes).

## 2026-07-15 13:40 JST — Claude (macOS): started a new sibling repo
`~/work/e07/e07-binary-segmentation` (same level as e07-fullscan)

Learned track/fog binary segmentation model -- the next lever after
all 5 classical noise filters plateaued (see analysis-note.md,
2026-07-15 entry). Reuses `module.reader`/`module.preprocess` from
this repo via a path reference (not duplicated). Side effect:
installed torch/segmentation-models-pytorch/torchvision etc. into
this Mac's shared pyenv 3.14.6 install, so they are importable from
e07-fullscan too. No changes to files in this repo besides the
analysis-note.md entry. Not yet committed to git in the new repo
(pending user confirmation).

## 2026-07-15 14:30 JST — Claude (macOS): repointed `fullscan-image`
symlink and mounted real E07 fullscan data read-only

User corrected the assumption that continuing with KISO (E373) was
fine: the project's actual optimization target is E07, and KISO's
background density measurably differs (~1.8-2x lower foreground
fraction than E07 at matching slices, see analysis-note.md). Mounted
KEK's E07 fullscan share via
`sshfs ... ~/mnt/e07-fullscan -o ro` (creating a mount point under
`/group` required sudo, which auto-mode blocked as scope escalation
-- switched to a home-directory mount point per user's choice).
`e07-fullscan/fullscan-image` now points there (the old
`/group/...` target didn't exist).

No code changes in this repo, only the symlink target and the
analysis-note.md entry. Any other agent writing code against
`fullscan-image/` should note both `E07/` and `E373/` exist
side by side under the mount.

## 2026-07-19 08:00 JST — Claude (macOS): recorded `specials_x20`
validation result

Re-ran `tests/test_specials.py` (known 9-event ΛΛ hypernuclei vertex
validation, `-m slow`): all 35 tests now pass. Updated the stale
docstring ("fails for most events") with a note hypothesizing the
2026-07-11 OpenCV5 HoughLinesP shape fix as the likely cause. Full
detail in analysis-note.md 2026-07-18 (14).
Files touched: tests/test_specials.py (docstring only),
analysis-note.md. No other files changed.

## 2026-07-19 10:30 JST — Claude (macOS): changed `fullscan-image`
symlink structure (adapting to a fuse-t NFS remount)

The previous sshfs mount (`~/mnt/e07-fullscan`) had disconnected;
user remounted via fuse-t NFS at `~/mnt/kek_e07` instead. This new
mount's root sits one level deeper than before (directly `MOD108/`,
equivalent to the old `fullscan-image/E07/`, no E373 sibling)
vs. the old `fullscan-image -> ~/mnt/e07-fullscan` (root had E07/
and E373/ side by side). Fix: `fullscan-image` is now a plain
directory containing a symlink `E07 -> ~/mnt/kek_e07`, so existing
code references to `fullscan-image/E07/...` keep working unchanged.
E373 is not wired up under the new mount (unused currently). Detail
in analysis-note.md 2026-07-19 10:30. Files touched:
fullscan-image/ (symlink structure only), analysis-note.md.

## 2026-07-22 JST — Claude (macOS): changed production Hough
`max_gap` 5 -> 40 (`config/default.yaml`, `diag_common.py`)

Changed `config/default.yaml`'s `viewer.hough_mg` (consumed by
`analyze_cli.py`'s KEKCC v6 batch pipeline and `app.py`'s viewer
defaults) from 5 to 40, and mirrored the same change in
`module/pipeline/diag_common.py`'s `TRACK_CFG`. Reason: built a
pixel-level ground-truth mask from the 512 existing manual segment
labels (223 confirmed "true" tracks, rasterized) and measured that
the old value (mg=5) missed ~54% of confirmed real track pixels
(recall 45.8%). mg=40 reaches 92.7% recall while a false-bridging
diagnostic (length>300px AND grain-density<0.02) stays at the same
low level as mg=20/30. Full detail in analysis-note.md 2026-07-22
(2). `module/pipeline/finder.py`'s `_HOUGH_MG` fallback default was
also changed 4->40 earlier the same day (still on a different
thr=20/ml=25 baseline than the yaml's thr=35/ml=30 -- that
inconsistency is unresolved).
Fast test suite (52 tests) passes after both changes;
`specials_x20` (-m slow) re-validation is running.
Files touched: config/default.yaml, module/pipeline/diag_common.py,
module/pipeline/finder.py, analysis-note.md.

## 2026-07-27 JST — Claude (macOS): handoff note for the kekcc
session, `HANDOFF_kekcc.md`

Created a handoff note at the repo root for moving heavy compute to
kekcc, from the macOS session (702bbb20-...) to the kekcc session
(d7a92435-...). Covers: current state of Methods A/B/C/D, the three
most important recent findings (CNN seed variance invalidating
earlier comparisons, production-parameter definitions scattered
across 5 locations, Method A's stage-4 being recall-only with
catastrophic precision), the kekcc environment survey, and
candidate work items for kekcc.

**Blockers found on the kekcc side**:
- `~/work/e07/fullscan` (note: NOT named `e07-fullscan`) is at
  `baa81a2`, far behind; two weeks of work missing, needs git pull.
- torch / sklearn / cv2 all absent (neither system python3.9 nor
  /opt/anaconda3 has them).
- `bsub`/`sbatch`/`qsub` are not on the login node's PATH and
  `/usr/share/lsf*` doesn't exist -- unclear whether the repo's
  LSF-based scripts (`scripts/kekcc_job.sh`, `cli_submit_kekcc.py`)
  still work. Confirming the batch system is the top priority.
- `e07-ml-binary-segmentation` is not cloned on kekcc.

Files owned: HANDOFF_kekcc.md (new). No other files changed.

## 2026-07-27 JST — Claude (macOS): three documentation changes
(new `STATUS.md`, parameters centralised in yaml, discussion log
archived)

Done at the user's request to cut cross-session handoff cost.

**1. New `STATUS.md` in both repos** (overwritten in place, never
appended) — the current-state summary to read first when starting a
session. analysis-note.md stays as append-only history. Both
CLAUDE.md files now document the rule.

**2. `module/pipeline/finder.py` now reads `config/default.yaml`**
instead of hardcoding defaults. The hardcoded values had drifted
from the yaml twice (`hough_mg`, `grain_radius`), silently degrading
detection both times. This also resolves the last remaining
mismatch (finder.py thr=20/ml=25 vs yaml thr=35/ml=30).
**Impact on other agents**: any code calling `find_tracks` without
explicit Hough parameters now gets different results (thr 20->35,
ml 25->30). Callers that pass parameters explicitly
(`analyze_cli.py`, `app.py`, `labeling.py`, `track_classifier.py`,
`diag_common.py`) are unaffected.

**3. Pre-2026-07-11 entries split out of `discussion.md` /
`discussion_ja.md`** into `discussion_archive_2026H1{,_ja}.md`,
verbatim. Live files shrank to 703/657 lines; verified zero entries
lost. CLAUDE.md's append-only rule gained an explicit exception
(user request only, verbatim archive, no content edits).

Files owned: STATUS.md (new, both repos), CLAUDE.md (both repos),
module/pipeline/finder.py, discussion{,_ja}.md,
discussion_archive_2026H1{,_ja}.md (new), analysis-note.md.
52 fast tests pass; `specials_x20` (-m slow) still running.

---

## 2026-07-27 20:10 JST — Claude (kekcc): handoff verified on real hardware — two corrections

Verified `HANDOFF_kekcc.md` against the actual kekcc environment (node cw07).
Two of its claims are wrong, and one new blocker appeared.

**Correction 1 — LSF works.** The note's top blocker ("bsub not in PATH; the
whole plan does not hold without resolving this") is wrong here: bsub exists
at `/opt/lsf/10.1/.../bsub`, LSF 10.1, cluster `centralcluster`. The note was
written on cw02, so this is a login-node or PATH difference.
`cli_submit_kekcc --dry-run` completes and emits a valid queue-`s` command
(135 jobs). Method A full-scan submission is ready to go.

**Correction 2 — repo is current.** Not `baa81a2`; HEAD is `f2b77d4`, in sync
with origin/main, tree clean. `~/work/e07/fullscan` is a symlink to the gpfs
checkout, not a second clone. (`e07-ml-binary-segmentation` is indeed absent.)

**New blocker — no GPU.** `bqueues -l g` shows the GPU queue is unusable three
ways: `USERS: shogo kmura ce_ibm/` excludes hayashu (`bqueues -u hayashu` =>
`s l h p a` only), STATUS is `Closed:Inact_A`, and the sole GPU host `ccg01`
is `unavail`. So candidate 1 (CNN LOTO on kekcc) loses most of its appeal —
CPU only. Usable queues are all MEMLIMIT 4 GB; `h` allows 8-day walltime and
TASKLIMIT 12, so CPU training is feasible there but `torch.set_num_threads()`
must be capped at 12 (torch otherwise sees 64).

**Environment change (user-approved).** Installed into conda `myenv`:
scikit-learn 1.6.1, scikit-image 0.24.0, torch 2.8.0+cpu, torchvision
0.23.0+cpu, with numpy pinned to 1.26.4 so the conda-built opencv 4.12.0 stays
intact. The note's "no torch/sklearn/cv2" survey had missed `myenv` (cv2 was
already there). Verified: all imports OK, `pytest -m "not slow"` 52 passed /
35 deselected, matching the historical baseline.

Files touched: `analysis-note.md` (2026-07-27 entry), this log and
`discussion_ja.md`. No commit — recording only, per the handoff's rule that
commits happen on explicit request.

---

## 2026-07-27 22:45 JST — Claude (kekcc): specials correction, rename, Method C env ready — blocked on manual_labels

**User correction (major).** 11 of the 13 `specials_x20/` directories are
**E07** emulsion with genuine reaction points: D005, D013, IBUKI, IRRAWADY,
MINO, T004, T004_3body, T004_center, T011, T011_100, T011_200. Only KISO and
NAGARA are E373 (deprioritised). Of the 9 events with measured GT in
`tests/specials_gt.json`, **7 are E07**. This retracts two STATUS.md
constraints ("specials_x20 is E373, do not optimise on it" and "real E07 has
zero confirmed vertices"). The ~1.8-2x foreground-density measurement from
2026-07-15 was KISO(E373) vs E07 full-scan data specifically, not a property
of specials as a whole.

**Directory renamed.** `~/work/e07/fullscan` -> `~/work/e07/e07-fullscan`
on kekcc, per user request, so both machines use the same name. This also
makes `e07-binary-segmentation/src/paths.py` resolve (it looks for a sibling
named `e07-fullscan`). 52 fast tests still pass. Stale references remain only
in append-only logs and `HANDOFF_kekcc.md`, which were left untouched.

**STATUS.md updated in both repos** (overwrite-in-place, per CLAUDE.md):
specials E07/E373 breakdown, the retracted constraints, kekcc environment
(bsub works / no GPU / myenv contents / numpy pinned), the 2026-05-14 staleness
of `results/`, and the mg=40 52x track-count blowup measured today.

**Method C now runs on kekcc.** Installed into conda `myenv`:
scikit-learn 1.6.1, scikit-image 0.24.0, torch 2.8.0+cpu, torchvision
0.23.0+cpu, segmentation-models-pytorch 0.5.0, matplotlib. Verified
`smp.Unet(resnet18, in_channels=1, classes=1)` forward on a 320x320 input and
the sibling `module.reader` / `module.preprocess` import. numpy held at
1.26.4 throughout so the conda-built opencv 4.12.0 stays intact.

**BLOCKER for macOS side.** kekcc has no training data and cannot generate
any. `e07-binary-segmentation/{data,results}` are macOS-local symlinks, and
the upstream source `e07-fullscan/results/manual_labels/*.json` (the 512 human
segment judgements) is not in git because `.gitignore` excludes `results/`.
kekcc's copy is empty. This blocks pseudo-label generation too, since
`scripts/generate_pseudo_labels.py` trains the classifier from those labels
at run time (`build_training_set(LABELS_DIR)`). The judgements are human work
and cannot be regenerated.

Request: make `results/manual_labels/` available on kekcc. Suggest adding a
`.gitignore` exception and committing it — the set is small, irreplaceable,
and needed on both machines. Otherwise a manual copy works.

Files owned this session: STATUS.md (both repos), analysis-note.md,
discussion{,_ja}.md. No commit yet.

---

## 2026-07-28 01:05 JST — Claude (kekcc): intent — LOTO training runs (Method C)

Launching leave-one-tile-out training on the work server cw07 (not LSF:
these are short now, and the 4 GB queue cap is irrelevant at ~1 GB/run).

Inputs (read-only): `e07-fullscan/results/manual_labels/*.json` (4 tiles,
512 human decisions) via `e07-binary-segmentation/data/real_labels/*.npz`,
regenerated tonight to carry the new orientation plane.
Outputs (new, all inside the ML repo): `results/loto/{arm}_{tile}_s{seed}.pt`
and `.log`, 24 combinations = 2 arms (binary-only, binary+orientation) x 4
held-out tiles x 3 seeds, 50 epochs each, 4 threads per process.
Owned files this session: in `e07-binary-segmentation` —
`src/real_label_dataset.py`, `src/real_dataset.py`, `src/train_real.py`,
`src/train.py`, `src/model_defaults.py` (new), `src/eval_segments.py` (new),
`scripts/run_loto.sh` (new), `STATUS.md`. In `e07-fullscan` — `STATUS.md`,
`analysis-note.md`, `discussion{,_ja}.md`. No writes to `e07-fullscan/results/`
beyond reading the labels, and no LSF jobs.

## 2026-07-28 02:10 JST — Claude (kekcc): correction — work server caps users at 4 cores; moving LOTO to LSF

The 01:05 plan to train on cw07 was wrong and is withdrawn. kekcc puts
CPU-heavy interactive processes into the cgroup
`/user.slice/restricted_user`, whose `cpu.max` is `400000 100000` --
**four cores total** for everything the user runs there, on a 128-core
node. `nr_throttled` is in the millions. Training looked fine for the
first two or three epochs (22 s each) and then dropped to ~370 s as the
throttle took hold, with the machine sitting 96% idle throughout. The
same pattern at 24, 12 and 6 concurrent processes, which is what made
it look like self-contention rather than an external cap.

Consequence beyond Method C: the "full Method A rescan takes ~6.5 h on
the work server at 16 workers" figure recorded earlier today was
measured before throttling and is optimistic by roughly 4x. The work
server is for editing and short tests, not for production compute.

Now submitting the same 24 runs as an LSF array to queue `h`
(78 pending vs 522 running, the least congested; `l` has 113k pending
and `s` 32k). Memory fits easily -- training peaks at ~1.3 GB against
the 4 GB queue cap. Inputs unchanged (`results/manual_labels/*.json`
via `data/real_labels/*.npz`). Outputs unchanged
(`e07-binary-segmentation/results/loto/{arm}_{tile}_s{seed}.{pt,log}`),
plus LSF stdout under `e07-binary-segmentation/logs/loto/`.
New owned file: `scripts/loto_job.sh`. Local `results/loto/` was
cleared of the throttled partial runs first.

## 2026-07-28 05:00 JST — Claude (kekcc): done — LOTO complete, CNN has no discriminative power

LSF array 54866034 finished: 24/24 runs, no failures, ~30 s/epoch on 4
cores per job, ~1.3 GB peak (limit 3.9 GB), 96% CPU efficiency.

**Result, pooled over 4 folds x 3 seeds (n=1536 segments, base rate
43.6%):** binary-only and binary+orientation both give precision 43.9%
[41.4, 46.4] with recall 98.5-99.0%. Precision equals the base rate in
every stratum (rank<=100: 70.3-70.5% vs base 70.4%; rank>1000:
14.6-15.4% vs base 14.6%). AUC is 0.43-0.56, so this is not a
misplaced threshold -- the scores carry no information.

**Root cause found.** Running a trained model over a real slice, it
marks **78.6% of the slice as track** (97.5% for the binary-only arm),
with probabilities never dropping below 0.34. The mask is `-1`
(excluded from the loss) for 99% of pixels, so the only negatives the
model ever sees are junk Hough segments -- thin line-like objects. It
is never shown empty emulsion, so it cannot reject background. The
2026-07-18 decision not to treat unreviewed pixels as 0 is right for
Hough *candidates* but was applied too broadly: pixels far from any
candidate are safely background.

Fix is small and is now the top item in the Method C STATUS.md: dilate
all candidate segments, mark everything outside as 0, re-run LOTO, and
see whether AUC moves off 0.5. If it does not, the wall is data volume
(3 training tiles).

The orientation head neither helped nor hurt the binary channel, which
at least confirms it is safe to keep. `extract_segments.py` works
(direction coherence 0.950 with a trained model vs 0.837 untrained) but
its output is physically meaningless while the mask covers most of the
image -- connected components fuse into 2,890 px "segments".

All work is committed to disk but NOT to git; 2 repos have uncommitted
changes for review. Files touched are listed in the 01:05 and 02:10
entries, plus `src/extract_segments.py`, `src/dump_segments.py`,
`src/eval_segments.py`, `src/model_defaults.py`, `scripts/loto_job.sh`,
`README.md` and `STATUS.md` in the ML repo, and `analysis-note.md` /
`STATUS.md` here.

## 2026-07-28 05:25 JST — Claude (kekcc): background-negative fix implemented, LOTO re-running

Implemented the fix identified at 05:00: `real_label_dataset.py` now
paints every Hough candidate with a 12 px brush and samples pixels
outside that as junk (`_sample_background`, 2 background pixels per
explicitly labelled pixel, seeded). Labelled coverage per tile goes
from ~0.95% to ~2.9% of the slice.

Smoke test (8 epochs, held-out V00000011) shows the intended change:

| | predicted-track area | prob median | prob min | val_recall |
|---|---|---|---|---|
| before | 78.6% of slice | 0.563 | 0.340 | ~99% |
| after | **14.3%** | **0.072** | **0.000** | 65-70% |

The model now rejects background confidently instead of marking nearly
everything as track. val_loss also drops from ~0.60 to ~0.37.

Re-running the full LOTO as LSF array 55017237 (queue h, same 24
combinations). Previous results and logs preserved as
`results/loto_nobg/` and `logs/loto_nobg/` for comparison; new ones go
to `results/loto/` and `logs/loto/`. Old npz kept as
`data/real_labels_nobg/`. Segment-level evaluation follows when it
finishes.

## 2026-07-28 07:40 JST — Claude (kekcc): done — background fix works but is not enough (AUC 0.54 -> 0.59)

LSF array 55017237 finished. Segment-level LOTO, 4 folds x 3 seeds,
n=1536 segments, base rate 43.6%:

| arm | precision | recall | predicted positive | AUC | before |
|---|---|---|---|---|---|
| binary | 49.5% [46.0, 53.1] | 55.8% | 49.0% | 0.582 | 0.549 |
| orient | 48.6% [45.3, 52.0] | 61.0% | 54.6% | 0.597 | 0.539 |

What improved: precision now sits significantly above the base rate
(both CI lower bounds clear 43.6%), where before it matched the base
rate exactly. Predicted-positive fell from 97.7% to 49.0%, and the
model marks 14.3% of a slice as track instead of 78.6%, with
probabilities reaching 0.000 instead of bottoming out at 0.340.

What did not: AUC 0.59 is only modestly better than chance. Within
each stratum the difference from the base rate is NOT significant
(top-100: 73.9% vs base 70.4%, CI lower bound 69.5). So part of the
overall AUC is just the model separating the top-100 stratum from the
tail rather than discriminating within either. **Report per-stratum
AUC as the primary number**, not the pooled one.

The orientation arm is now slightly ahead of binary-only (0.597 vs
0.582 overall, 0.593 vs 0.550 in the top stratum). Inside the CI, so
not a claim -- but it is no longer indistinguishable, and it does no
harm.

`extract_segments.py` also improved: 680 segments (was 144), median
length 27.9 px (was 15.8), longest fused component 1,246 px (was
2,890). Still 355 of 680 flagged as crossings/blobs, so
connected-component splitting remains weak; the orientation field is
the natural tool for that next.

Remaining wall is data volume: only 3 tiles are available for
training, and overfitting is unresolved (train_loss 0.026 vs val_loss
0.98). Next step in the Method C STATUS.md is more labels, with the
E07 specials' vertex-radiating tracks as a non-circular source.

Nothing committed to git; both repos hold uncommitted changes for
review. Old no-background results kept at `results/loto_nobg/`,
`logs/loto_nobg/`, `data/real_labels_nobg/`.

## 2026-07-28 09:00 JST — Claude (kekcc): specials as a new label source, LOTO running

Acting on the top next-step: more labels, from the E07 specials rather
than from more human clicking.

**Method.** A segment whose line passes within 10 px of a confirmed
reaction vertex and whose nearer endpoint is within 150 px of it is
very likely a real track from that event. The judgement comes from
geometry plus a physics-confirmed vertex, not from a human grading
Hough's output — so unlike pseudo-labels it does not feed the Method A
classifier's opinion back to the CNN. Hough still proposes the
segments; what changes is who decides they are real.

**Purity is measured, not assumed.** The same cut is scored at 12
random control points per event, and an event is used only if the true
vertex selects >=3x the control median:

| event | candidates | selected | control med | contrast | |
|---|---|---|---|---|---|
| D005 | 4569 | 42 | 6.0 | 7.0x | keep |
| D013 | 3340 | 27 | 3.5 | 7.7x | keep |
| IBUKI | 8074 | 32 | 16.0 | 2.0x | **skip** |
| IRRAWADY | 8510 | 45 | 12.5 | 3.6x | keep |
| MINO | 4850 | 40 | 8.0 | 5.0x | keep |
| T004 | 4066 | 30 | 6.0 | 5.0x | keep |
| T011 | 2472 | 30 | 1.5 | 20.0x | keep |

IBUKI is dense enough that a random point selects nearly as many
segments as the true vertex, so it contributes mostly accidents and is
dropped. Six events kept, 214 positive segments, implied purity
roughly 70-95% depending on event.

**What this buys** is less the extra positives (27k track pixels
against 139k) than the tile diversity: training tiles go from 3 to 9,
against overfitting that currently drives train_loss to 0.026 while
val_loss sits at 0.98.

New file: `src/specials_label_dataset.py`. `train_real.py` gains
`--specials`; those tiles are TRAINING only and never enter the
validation split, which stays on human decisions. `pos_weight` now
counts them (3.73 vs 4.16).

Inputs (read-only): `/gpfs/group/had/sks/Users/shuhei/work/specials_x20/
<event>/image.json` and `e07-fullscan/tests/specials_gt.json`.
Outputs: `e07-binary-segmentation/data/specials_labels/*.npz` (6 files)
and LSF array 55277503 writing `results/loto/` + `logs/loto/`.
Previous background-fix results archived as `results/loto_bg/` and
`logs/loto_bg/`; the pre-background ones remain in `results/loto_nobg/`.

## 2026-07-28 19:55 JST — Claude (kekcc): done — specials labels are a NULL result (AUC 0.592 -> 0.594)

Controlled A/B, four folds at one seed per arm, 20 epochs, n=512
segments, base rate 43.6%:

| | precision | recall | predicted positive | AUC |
|---|---|---|---|---|
| without specials | 48.0% [42.7, 53.4] | 70.4% | 63.9% | 0.592 |
| with specials | 50.0% [43.7, 56.3] | 54.3% | 47.3% | 0.594 |

Per-stratum AUC: top-100 0.555 -> 0.560, tail 0.538 -> 0.543. Training
tiles went 3 -> 9 and discrimination did not move. The
precision/recall changes are only an operating-point shift, which is
exactly what AUC controls for.

**Power caveat, stated up front:** at n=512 (223 track / 289 junk) the
Hanley-McNeil SE on a single AUC is 0.025, so the smallest detectable
difference is **0.070 AUC**. This experiment rules out a large gain,
not any gain.

The baseline here (20 epochs, 1 seed, AUC 0.592) reproduces this
morning's 50-epoch 3-seed result (0.597), so the shortened setup is
sound.

**Interpretation.** The specials supply positives only. The hard
distinction is line-like junk versus line-like track, and they say
"this one is real" without adding a single junk example — while the
model already over-predicts track (positive rate 64% even after the
background fix). What was missing was never more positives; it is
information that separates junk from track. Tile diversity not helping
fits the same reading.

**Where this leaves the plan.** Cheap geometric labelling is capped on
the positive side. Remaining options: (1) more junk-side supervision,
which means human review — but reviewing where classical and ML
DISAGREE maximises information per click; (2) a different signal
entirely — cross-slice 3D consistency, grain density — since a single
slice's appearance may not separate junk from track even in principle,
which AUC 0.59 may be telling us.

Ran on the work server under its 4-core cap (8 runs, ~4.5 h) because
LSF would not schedule: this user's fairshare priority is 0.000 in
every queue after 400+ jobs in queue l, and queue s additionally caps
CPU at 150 min, which fits only ~12 epochs of the 9-tile set. The
3-seed LSF version is still queued and will strengthen the statistics
if it ever starts.

New/changed: `src/specials_label_dataset.py`, `--specials` in
`train_real.py`, `scripts/run_local_ab.sh`, `scripts/loto_job.sh`.
Results under `results/local_{sp,nosp}/`. Still nothing committed.

## 2026-07-29 12:45 JST — Claude (kekcc): /label_disagree added; found and fixed a label-corrupting bug

Acting on "what's missing is junk-vs-track information": added a
browser queue that shows candidates in order of how much the classical
classifier and the CNN disagree.

**Measured before building.** Over 47,498 candidates on the four
labelled tiles at production Hough parameters, the two reach opposite
verdicts on **30.2%** (14,341), 9.3% differ by more than 0.5 in
probability and 396 by more than 0.7. The queue is thick enough to be
worth the UI.

**Implementation.** `/label_disagree` (+ `/label_disagree_segments`)
reuses the `/label_uncertain` template — endpoint and label are now
template variables rather than a copy. CNN probabilities come from a
file (`e07-binary-segmentation/data/cnn_scores.json`) so torch never
enters the Flask process; produced by `dump_segments.py
--all-candidates --hough 35,30,40` then the new `score_candidates.py`.

**Latency 84 s -> 0.12 s.** Two things were recomputed on every
request even though neither depends on the labels: per-tile Hough plus
features for ~12,000 segments, and `build_training_set()` re-running
Hough over every label file's tile. Both are memoised now
(`labeling._cached_features`, `track_classifier.features_for_record`).
First request still ~80 s to warm; `/label_uncertain` got the same
speedup.

**Label-corrupting bug, found and fixed before it fired.**
`label_decide` stamps the CURRENT Hough parameters onto the record it
writes. Review defaults moved to 35/30/40 on 2026-07-23; all 512
existing decisions were recorded under 8/10/20 and untouched since
2026-07-18. A decision is an index into the candidate list, so one new
click would have rewritten the parameters and silently repointed all
512 at a different candidate set (24,038 vs 12,003 entries, ordered
independently). Nobody had clicked since the switch, so nothing was
lost. Fixed by giving each parameter set its own file: matching
parameters append to the existing file, different ones go to
`..._z29__t35l30g40.json`. Verified end to end — a new decision landed
in the new file, the legacy file's md5 was unchanged, all 512
decisions intact. `real_label_dataset.py` already reads parameters per
file, so both sets stay usable.

**Note for whoever labels next:** new decisions accumulate on the
35/30/40 candidate population, which is NOT the same population as the
old 512. Do not add them up as one number.

Changed: `module/server/labeling.py`, `module/track_classifier.py`,
`README.md`, `STATUS.md`, `analysis-note.md` here; new
`src/score_candidates.py` and `--all-candidates`/`--hough` in
`src/dump_segments.py` in the ML repo. 52 fast tests pass. Server for
review: `python -m module.server.app --port 8123`. Still uncommitted.

**Result (same day)**: done. Fed the reference `lseg`, the port returns
**exactly 149 polylines**, total length 118,270 px (reference 118,033,
0.2% apart), every polyline within 16 px of a reference one. From raw
hits: 24.5 s/view (stage 1 14.0 + stage 2 10.5). 63 fast tests pass,
2 slow tests pass.

**Unlike Phase 1-1, bit-exactness is unreachable** -- and was shown to
be. `resamplingpoly` selects hits with `ell>=0`, but a polyline's end
vertex is by construction the projection of its own outermost hit, so
that hit sits exactly on the boundary. Measured: **all 175 chains carry
one such hit (`|ell|<1e-8`) at each end**. MATLAB's and NumPy's BLAS
disagree in the last bit there, moving the endpoint by ~1 px. Swapping
`np.linalg.norm` for `dnrm2` only moved the match count 97 -> 99, so it
is ulp-level noise, not one formula. The port always includes those
hits (`_ELL_SLACK_PX = 1e-9`). The literal version gives 150 polylines
and a 76 px worst case; always excluding them starves a polyline of
hits and raises. The chosen variant matches the reference count and
caps the worst case at 16 px.

**The measure changed too**: Hausdorff distance between the curves
after 1 px resampling, not vertex-list equality -- otherwise an
identical track whose corner vertex sits a few hits over counts as a
mismatch.

**Three defects found in the MATLAB source** (detailed in
analysis-note.md 2026-09-07): the `kousinflag`/`koushinflag` spelling
split, a final assignment that errors if any polyline is dropped, and
the flag=2/3 branches building an all-pairs distance matrix that cannot
scale to a view.

Changed: `module/graphdet/{integrate,polyfit,geom,__init__}.py`,
`scripts/check_polylines_reference.py`, `tests/test_graphdet.py`,
`README.md`, `STATUS.md`, `analysis-note.md`. Still uncommitted.

## 2026-09-07 — Phase 1-3: porting `detectbunki` and the first efficiency/purity measurement

**Inputs (read-only)**: `e07/matlab/detectbunki.m`,
`e07/matlab/simdata8.mat` (`Summary` for 10 events, `dspl` hits).
**Outputs (new, owned by this repo)**: `module/graphdet/branch.py`,
`scripts/eval_branches.py`; updates to `__init__.py`,
`tests/test_graphdet.py`, `README.md`, `STATUS.md`, `analysis-note.md`.

**Result**: all three stages are now ported. Against the 130 true branch
points of the 10 simulation events, matching at 25 px isotropic:
**efficiency 96.2%, purity 74.0%** (93.1% / 55.3% at 10 px). Efficiency
is fine; purity is the weak side — 215 vertices found for 130 real ones.
4 of the 125 matched truths collapse onto a shared reconstructed vertex,
so the resolution is worse than the efficiency figure suggests.

**Two porting judgements**:
- MATLAB's `linkage` + `cluster` at a 0.5 cutoff over a 0/1 distance
  matrix is, for the default single linkage, exactly connected
  components. Replaced the dense M x M distance matrix with a BFS.
- `branch_points()` is an **addition, not a port**. detectbunki returns
  groups and never coordinates, but coordinates are what E07 needs, so
  they are derived from the shared hits the grouping already uses.

**One more MATLAB defect**: a degenerate zero-length segment makes
`v./norm(v)` NaN, which `min` normally skips — but when EVERY candidate
is NaN, `min` returns NaN with index 1 and `~isinf(NaN)` is true, so it
joins on a NaN distance. The port rejects degenerate segments outright.
Event 1, the one used for the stage-2 reference check, has no
zero-length segments, so that check is unchanged.

**Timing caveat**: events 6-10 took ~5x longer than events 1-5, but all
three stages slowed by the same ratio — that is the work server's 4-core
cap, not the data. The unthrottled figure is 24.5 s/view.

68 fast tests pass. Still uncommitted.

## 2026-09-07 — Phase 2: calibrating the export grid; 30 px measured to be far too coarse

**Inputs (read-only)**: `e07/matlab/{mabiki.m,simdata8.mat}`.
**Outputs (new, owned by this repo)**: `module/graphdet/{config,downsample,
simeval}.py`, `scripts/scan_sampling.py`; updates to
`module/graphdet/{geom,detectlseg,integrate,branch,__init__}.py`,
`module/matlab_export.py`, `tests/test_graphdet.py`, `README.md`,
`STATUS.md`, `analysis-note.md`.

**Conclusion**: `matlab_export._GRID_CELL_PX = 30` drops branch-point
purity from 78.8% to 17.5%. Measured by re-thinning the same simulation
at other block sizes — the truth comes from `Summary`, so it survives
the thinning. The knee is at 6 px. The 30 px value was chosen on
2026-07-11 to keep MATLAB near 2.5 h/tile; the port is ~250x faster, so
that constraint is gone. `_GRAPH_CELL_PX = 6` is now the export and CLI
default, with `noise_cell` keeping the noise filters at their own
separately tuned 30 px.

**Which stage breaks**: stages 1 and 2 survive the coarse grid (98% of
track length, all 14 true vertices still have a polyline vertex within
25 px). Only stage 3 fails, and no constant fixes it: detectbunki
decides a branch from hits shared within 1.5 px, which a coarse grid
removes. A geometric alternative (polyline endpoint near another
polyline) was prototyped and rejected — it restores efficiency to 83%
but purity only to 26%.

**Scaffolding**: `DetectorConfig` collects every distance constant. Its
organising idea is the split between transverse tolerances and length
scales; `for_spacing()` rescales only the latter. Defaults are the
MATLAB values, so all reference checks are unchanged (stage 1: 1,239/1,239
segments, worst 2.5e-13 px; stage 2: 149 polylines; stage 3: 92.9%
efficiency / 92.3% purity). `mabiki.m` is ported too and reproduces the
stored `dspl` exactly.

**Unmeasured risk**: the cost of 6 px on real E07 data. The simulation
has 159 tracks per view and real E07 is far denser — measure one tile
before running an export for real. `z_scale` is also still the MATLAB
value; `E07_Z_SCALE` is defined but not yet the default.

**Timing caveat**: the work server's 4-core cap made the later sweep
rows 3-5x slower than the earlier ones. Do not trust the absolute times.

22 fast graphdet tests pass, 2 slow. Still uncommitted.

## 2026-09-08 — Running the graph detector on a real E07 tile; the Method A / LSF constraint is retracted

**Inputs (read-only)**: one real E07 tile
`.../IMAGE00_AREA00/V00000000_L0_VX0000_VY0000_0_058.{json,spng}`,
`e07/matlab/simdata8.mat`.
**Scratch outputs (outside the repo, in `~/private/tmp/`)**:
`e07_pl_cell{6,30}.npy`, `e07_seg_cell30.npy`, `e07_poly_cell30.npy`,
`memtest.parquet`, `mg5.parquet`, `vtx_*.parquet`.
**Changed (owned by this repo)**: `module/graphdet/{detectlseg,integrate,
branch,geom,config}.py`, `config/kekcc.yaml`, `scripts/kekcc_job.sh`,
`tests/test_graphdet.py`, `README.md`, `STATUS.md`, `analysis-note.md`.

**1. It runs end to end on a real tile, ~45 min/view.** Three exact
optimisations got it there, with every reference check unchanged:
recompute only the moving segment's column when refining endpoints
(176.9 -> 4.23 s on an 800-hit region, exponent 2.6 -> 1.6); a k-d tree
for the endpoint box query; neighbourhood queries instead of scanning
every hit in `_resample` and `attachment_codes`. Stage 3 additionally
needed a sparse representation -- its dense codes matrix was 7 GB and
`branch_points` looped over 840 million polyline pairs.

**2. `for_spacing()` was scaling the wrong group.** Scaling everything
widens the endpoint search box from 50 to 500 px, and real-tile stage 2
never finished in 60 minutes. Measured on the simulation at 6 px:
90.2/66.0 (scale all) vs 87.8/**75.5** (spacing only) vs 85.4/75.9
(none). Purity is the weak side, so spacing-only wins. Real-tile stage
2: over 60 min -> **154 s**.

**3. The limit is track density, not grid size.** Real E07 at 30 px
gives 28,988 polylines where the simulation gives 149, and 8,118 branch
points where it gives 13. 6 px is worse -- one sub-region alone exceeds
25 min in stage 1. Next: cut density at export time, or shrink
`REGION_PX` so a sub-region holds the ~163 hits the constants assume.

**4. Method A can go to LSF after all** (July's conclusion retracted).
`config/kekcc.yaml` and `scripts/kekcc_job.sh` had three fatal bugs: the
input path was missing its `E07/` level, the job script called a
non-existent `module.analyze`, and `n_jobs: 135` blew the memory cap.
Measured: 1 view is **1.55 GB** and ~2 min; July's "6.75 GB" was four
views in one job. Now `n_jobs: 2025`, output `results/fullscan_v7`.
**Not submitted** -- submission awaits an explicit request.

**5. The mg=40 impact on stage 4 is measured** (the precondition for the
full re-analysis). One real view: 193 -> 2,533 candidates (13.1x). But
mg=5 yields **zero** candidates with n>=8 while mg=40 yields 66 --
high-multiplicity stars were structurally invisible before.

22 fast graphdet tests pass. Commits 1717a10, 35e52a7, b2e79fe,
dd393d1 and the follow-ups.

**Addendum (same day, 22:00): the density wall is passed.** The "6 px is
not realistic" conclusion above is retracted. (1) Switching the export's
`denoise_method` to the classifier mode -- using the classifier already
trained on the existing labels, no new human input -- cuts 6 px hits
from 1,667,324 to **784,522**. (The `threshold` mode is looser than
`legacy` and ten times slower; there is no reason to use it.) (2)
`_merge_overlapping` now answers "is any other segment claiming this
hit" for all segments at once; after the refine_endpoints fix it was 85%
of stage 1, and a 3,013-hit sub-region goes from 331.8 s to **39.0 s**.
Together, 6 px is **~2.77 h/view** for stage 1, ~3 h/view in total, with
stage 1 peaking at 0.3 GB. Simulated purity there is **75.9%** against
17.5% at 30 px. Reference checks unchanged (1,239/1,239 at 2.5e-13 px).
The 6 px end-to-end run has NOT been done -- it belongs on LSF queue
`h`. Commit e763a36.

## 2026-09-09 — Method A full re-analysis: 20-view pilot submitted

**Inputs (read-only)**: `/gpfs/group/had/sks/E07/tohoku/fullscan/E07/MOD108/
PL12/tohoku-v1/AREA00/IMAGE00_AREA00` (2025 views).
**Outputs (new, owned by this session)**:
`results/fullscan_v7/chunk_0001..0020.parquet`,
`logs/kekcc/job_{1..20}.{log,err}`, `logs/kekcc/analyze_00{01..20}.log`.
**Changed (owned by this repo)**: `module/pipeline/lsf_queue.py` (new),
`module/pipeline/cli_submit_kekcc.py`, `config/kekcc.yaml`.

**The queue is chosen at submission time** (`queue: auto`). KEKCC queue
load changes by the hour: on the evening of 2026-09-08 queue `h` had
nothing pending; by 2026-09-09 it had 2,820. The selector takes only
queues `bqueues -u <user>` says are submittable, drops any whose CPU,
wall or memory limit cannot hold one job, and ranks by how many jobs
could start now (the smaller of the per-user slot limit and the free
slots, over n_cores) then by backlog. This time it picked **`p`**
(120 startable, 0 pending).

**20-view pilot first** (`--array 1-20`; `--chunk-total` stays 2025, so
the pilot is a real slice of the same partition and its output is not
wasted). The rest follows once it checks out.

Output goes to a separate directory from the 2026-05-14 mg=5 products.

**Pilot result (2026-09-09 00:35, job 94622705, queue `p`): 20/20 clean.**
125-134 s CPU per job (faster than the work server's 277 s, which was
throttled), **MAX MEM 1.2 GB** against the 4 GB cap, 13.4-14.3 MB output
per view. Submitted 00:32, all finished 00:35. `chunk_0001` matches the
local run of view 0 exactly at 634,577 tracks. No stderr -- the errors
visible in `logs/kekcc/job_*.err` were leftovers from 2026-05-09 and
have been moved to `logs/kekcc/archive_2026-05/`.
→ Submitting the remaining 2,005 views (`--array 21-2025`). Full-run
estimate: ~73 CPU-hours, ~28 GB output, ~40 min wall on queue `p` at
120 concurrent.

**Full run complete (2026-09-09 01:43)**:
stage 3 `results/fullscan_v7/` = **1,244,606,615 tracks** (2,025 chunks,
no gaps, no empty files, 26 GB); stage 4
`results/vertex_v7/vertex_*.parquet` = **16,728,649 candidates**
(572 MB), merged into `vertices.parquet` (464 MB) and
`vertices_merged.parquet` = **1,516,569 vertices** (`--min-slices 2
--min-tracks 8`, 62 MB). **About 1.5 hours from submission to the
finished catalogues.** The LL pair search
(`module/pipeline/pairs.py`) was retired on 2026-05-14, so the current
pipeline ends here.
**1.52M merged vertices is the stage-4 precision problem at full
scale** -- confirmation that a physics-based filter (PID, vertex
kinematics) is required rather than optional. The old `results/`
(2026-05-14, mg=5) is left in place.

## 2026-10-23 15:10 JST — Claude (e07-srv): intent — fix the z test in specials matching; move to e07-srv

**Context**: the user bought the GPU host e07-srv (Ryzen 9 9900X /
122 GB / RTX 5070 Ti) and wants stage 4 (vertices) done here rather
than on kekcc. All 2,025 tohoku-v1 views (307 GB) are local. kekcc's 3
unpushed commits (`ecd9570`..`85678b5`) were fast-forwarded into local
main, and the small `results/` products (`graphdet_specials/`,
`rank_specials.json`, `specials_merged/`, `vertex_crops_v6*_labels.csv`,
`vertex_v7/`) were copied from kekcc (kekcc unchanged).

**Bug (raised by Codex, confirmed on the data)**: the z test in specials
matching is a no-op. Image JSON z is stage mm (step 0.0030) and so is
`z_mean`, but `tests/specials_gt.json` `z_um` holds mm values rounded to
0.1 mm and is compared with `tolerance_z_um = 30`, i.e. "within 30 mm".
Affects `rank_specials.py` and `tests/test_specials.py`.

**Change**: take the true z from the clicked slice `z_slice` via
`reader.z_positions()` and compare in mm (30 um = 0.030 mm). The
physical z step (3.0 um stage vs 1.5 um in emulsion) is being asked of
the user, so this stays a stage-coordinate comparison.
**Owned files**: `scripts/rank_specials.py`, `tests/test_specials.py`,
`tests/specials_gt.json` (comment only), output
`results/rank_specials.json`.
**Job**: re-run `rank_specials.py` on e07-srv (minutes).

## 2026-10-23 15:34 JST — Claude (e07-srv): addendum — also own `rank_features.py`; z test is "inside the z span"

Per Codex, `scripts/rank_features.py` is added (owned). It picked the
truth as **the max-n_tracks_max candidate** within 200 px before ranking
each feature, favouring n_tracks_max. The truth is now the XY-nearest
candidate, independent of the feature; ties are shown as a range, and
the best rank of any matching candidate (equally generous to all
features) is reported too.

The z test in all three files is now "the clicked depth lies within the
candidate's `z_min`..`z_max` (+-30 um)", not `z_mean`. A star's tracks
leave the vertex towards one side in z, so z_mean is off by about half
the span; `z_mean` +-30 um puts IBUKI at rank 95, a bias of the test.
Results go to analysis-note.

## 2026-10-23 15:45 JST — Claude (e07-srv): intent — prepare a stratified random audit of v7 vertex candidates (no labelling yet)

Following Codex's proposal (2026-10-23), prepare **the sample and the
review screen** for measuring stage-4 precision. Whether to start the
human review is the user's call.
**Inputs (read only)**: `results/vertex_v7/vertices_merged.parquet`
(copied from kekcc), raw images under `fullscan-image/`.
**Strata**: within each view, the top 20 by `n_tracks_max` and the top
20 by `angle_spread_best x n_slices` (ties included) give four
exclusive strata (both / n_tracks only / sp x nsl only / neither); 100
drawn at random from each (fixed seed, inclusion probability stored).
**Outputs (new, owned)**: `scripts/vertex_audit.py` (sample / render),
`results/vertex_audit_v7/` (`key.csv` = stratum and ranks, `blind.csv`
= what the reviewer sees, `crops/` = montage PNGs of slices across z).
**Change (owned)**: `--categories` for
`module/pipeline/cli_review_crops.py` (default stays good/bad/unclear;
the audit uses vertex/crossing/junk/unclear). README and pipeline.md
updated if affected.

## 2026-10-23 16:10 JST — Claude (e07-srv): addendum — audit fixed after Codex review, 40-candidate pilot, GPU direction

`scripts/vertex_audit.py` fixed after Codex's review (margin direction
on the z range, marker position for edge candidates, no key overwrite
or stale PNG reuse, ties broken at random so both rankings spend the
same budget, every slice rendered). `cli_review_crops.py` gained
**slice stepping** (`/slices/<name>`, W/S, P) and a path-escape guard
on `/crop/`. A 40-candidate pilot (10 per stratum) is rendered in
`results/vertex_audit_v7/crops/`. No labelling yet.

**User direction (2026-10-23)**: kekcc may still be used, but **move to
GPU (e07-srv) implementations where possible**. Speeding up B' stage 1
is designed as a GPU port first, not CPU/LSF parallelism, keeping a CPU
path.

## 2026-10-23 16:19 JST — Claude (e07-srv): intent — speed up graphdet stage 1 (incremental `_merge_overlapping`, then GPU)

Profiled stage 1 on V00000991 (cell 6 + classifier, 754,765 hits,
median 2,972 per region) on e07-srv. In the densest region (5,464 hits)
`_merge_overlapping` is 73 s of grow's 75 s: it recomputes the overlap
matrix EᵀE after every merge although only two columns change. Make it
**incremental** (integer counts, so results are unchanged; checked
against the reference). Then batch the endpoint-refinement candidates
(`membership_from_segments` over all shifts at once) on the GPU with
torch, keeping the CPU path.
**Owned files**: `module/graphdet/detectlseg.py`, (for the GPU part)
`module/graphdet/geom.py`, `tests/test_graphdet.py`.
**Jobs**: measurements on e07-srv only (scratch outputs).

## 2026-10-23 16:44 JST — Claude (e07-srv): intent — batch `_footprint_width` and run it on the GPU (export speed)

Stage 1 with the incremental merge, batched candidates and the
near-hit restriction: densest region 94 s -> ~14 s (bit-identical
output, MATLAB reference tests pass). The export is next: 540 s per
view on V00000991, 13 of each slice's 16.5 s in
`finder._footprint_width` (a Python loop per segment, ~23k segments
per slice). Add `footprint_widths(tracks, binary, device=None)` that
does all segments at once, on CUDA via torch when available, numpy
otherwise. Coordinates are float64 with the same operation order as
np.linspace/np.round, so results are unchanged.
**Owned files**: `module/pipeline/finder.py`, `module/track_classifier.py`,
new test files under `tests/` if any.

## 2026-10-23 17:45 JST — Claude (e07-srv): done — stage 1 and export speed-ups (bit-identical)

Stage 1: incremental `_merge_overlapping` (row maxima, row counts,
shared counts), batched endpoint candidates scored only inside their
bounding box, thin SVD (`geom.right_vectors`),
`detect_lseg_view(workers=N)`. Export: `finder.footprint_widths` (GPU)
and a GPU screen in `_measure_tracks`. New `module/device.py`
(`E07_DEVICE`). V00000991: stage 1 106 s (12 workers), export ~100 s.
Output bit-identical to before, `tests/test_graphdet.py` (incl. slow)
passes, Method A `find_tracks` identical on CPU and GPU. Details in
analysis-note.

## 2026-10-23 17:49 JST — Claude (e07-srv): intent — check Method A on e07-g4-hypernuclei pseudo images

Read the 5 events x 2 versions (physical z step 3.0 / 1.5 um) made by
the e07-g4-hypernuclei session with SpngReader and run Method A as in
`rank_specials.py` (production and relaxed cuts) to produce candidate
CSVs. **Inputs (read only)**: `~/work/e07-g4-hypernuclei/data/images/nagara5_dz{3.0,1.5}/`.
**Outputs (new)**: `results/sim_eval/nagara5_dz*_methodA_{production,relaxed}.csv`.
Script in scratch (no repo change).

## 2026-10-23 18:02 JST — Claude (e07-srv): intent — redo B' specials with fixed settings and the same z test

kekcc's `results/graphdet_specials/` used a different cell (6/8/10/16)
and z window per event and matched in XY only (Codex). Add `--cell`
(fixed, no widening) and `--workers` to `scripts/graphdet_specials.py`,
map branch-point z back to stage mm (window offset, 1-based index) and
match within 200 px XY and +-30 um of the clicked depth. Run on e07-srv
at cell 6 for all 9 events.
**Owned file**: `scripts/graphdet_specials.py`.
**Outputs (new)**: `results/graphdet_specials_e07srv/` (kekcc's kept).

## 2026-10-23 18:14 JST — Claude (e07-srv): progress — audit hand-off ready; Method A on pseudo images

Audit (Codex's points): one contrast stretch per candidate,
`render_info.csv`, time / note / seconds per label (also fixes the ts
column that was always empty), `vertex_audit.py recheck` (20% blind
second pass), reviewer guide `results/vertex_audit_v7/INSTRUCTIONS_ja.md`.
Display regression-checked at specials truth positions and at the image
edge (the marker sits on D005's star apex).
Pseudo images (e07-g4-hypernuclei): dz=1.5 finds most capture vertices,
dz=3.0 almost none; far fewer candidates than real data (~750/view).
Image statistics gaps (binary foreground 8.6% vs 1.3%, etc.) sent to
that session; efficiency estimates wait until realism is matched.

## 2026-10-23 19:32 JST — Claude (e07-srv): intent — Method A and B' on v3 pseudo images

The e07-g4-hypernuclei calibrated model v3 (embedded in real views =
main, and fully synthetic), 5 events x 2 versions: Method A on all, B'
(cell 6 + classifier, 12 workers) on the embedded ones. Outputs
`results/sim_eval/v3_*_{methodA_*,bprime}.csv`. Scripts in scratch.
The B' specials redo is still running (D005).

## 2026-10-23 20:29 JST — Claude (e07-srv): change — `z_best` column in `merge_vertex_slices`

On e07-g4-hypernuclei pseudo images with truth, Method A candidates are
accurate to a few um in XY but their z-span ends are no closer to the
vertex depth than chance. Add `z_best`, the z of the slice with the
most tracks (the merge seed); existing columns unchanged. **Owned**:
`module/pipeline/vertex.py`, `pipeline.md`. The 100-event Method A
run is restarted to include it.

## 2026-10-23 21:45 JST — Claude (e07-srv): progress — 100-event pseudo-image evaluation; B' specials done

Agreed the matching spec with e07-g4-hypernuclei (edge / inclusive /
best, one-to-one, random-shift chance control) and evaluated Method A on
v3 embedded 100 events x 2 versions. B' specials redo (9 events) done.
Details in analysis-note. Remaining Method A (ll11be, ibuki, replay) and
B' (v3 dz1.5, replay) still running.

## 2026-10-23 22:19 JST — Claude (e07-srv): intent — Method A on the unmodified background views (control)

Requested by e07-g4-hypernuclei. Run Method A with the pseudo-image settings (rank_specials cuts, min_slices=1, with z_best) on the 98 source views of the v3 embedding (`background_views_v3_embed_nagara_dz3.0.csv`). Output `results/sim_eval/v3_bgonly_nagara_methodA_{production,relaxed}.csv`. Scripts in scratch.

## 2026-10-23 23:20 JST — Claude (e07-srv): done — autonomous evaluation closed; waiting on the user

Method A (8 v3 datasets + background control) and B' (nagara5 x2, replay 10 events each) finished. No jobs running. Next: the 40-candidate human audit and the user decisions.

## 2026-10-24 00:25 JST — Claude (e07-srv): intent — Method A on v4 synthetic; B' on 20 more embedded events

Requested by e07-g4-hypernuclei. (1) Method A (production / relaxed, with z_best) on v4_synth_nagara5_dz3.0 (5 ev), v4_synth_nagara_replay_dz3.0 and v4_synth_ibuki_replay_dz3.0 (10 ev each) -> `results/sim_eval/<ds>_methodA_{production,relaxed}.csv`. (2) Then B' (cell 6, 12 workers) on v3_embed_nagara_dz3.0 ev0000-0019 -> `results/sim_eval/v3_embed_nagara_dz3.0_bprime.csv` plus `.done` at the end (~2 h). Scripts in scratch; no repo code changes.

## 2026-10-24 02:35 JST — Claude (e07-srv): done — v4 Method A; B' 20 embedded events

Method A on the three v4 synthetic datasets finished (production ~795 candidates/view, relaxed ~900, vs ~40 for v3 synthetic and ~770 real). B' on v3_embed_nagara_dz3.0 ev0000-0019 finished (~29k branch points/event, 250-880 s/event); `.done` written. Evaluation is with e07-g4-hypernuclei.

## 2026-10-24 JST — Claude (e07-srv): intent — Method A on v11 synthetic

Requested by e07-g4-hypernuclei. Method A (production / relaxed, with z_best) on v11_synth_nagara10_dz3.0, v11_synth_nagara_replay_dz3.0, v11_synth_ibuki_replay_dz3.0 (10 ev each) -> `results/sim_eval/<ds>_methodA_{production,relaxed}.csv`. Scratch scripts; no repo code changes.

## 2026-10-24 04:16 JST — Claude (e07-srv): done — Method A on v11 synthetic

All three v11 datasets finished (10 ev each): production ~905 candidates/view, relaxed ~973 (v4 ~795 / ~900, real ~770). Evaluation is with e07-g4-hypernuclei.

## 2026-10-24 04:32 JST — Claude (e07-srv): intent — dump B' branch points for specials (darkness-ranking check)

e07-g4-hypernuclei found that ranking B' branch points by local image darkness beats Method A on pseudo images. To test it on real known events, `scripts/graphdet_specials.py` (owned by me for this change) will also write `<event>_points.csv` (vx_px, vy_px, slice, z_mm, mult). Rerun the 9 specials with `--cell 6` into `results/graphdet_specials_e07srv/` (~1-2 h); the JSON summaries should come out unchanged.

## 2026-10-24 05:54 JST — Claude (e07-srv): done — specials B' branch points dumped

All 9 specials rerun with `--cell 6`; JSON summaries identical to the 2026-10-23 run (apart from seconds). `results/graphdet_specials_e07srv/<event>_points.csv` now holds every branch point (225k in total). Handed to e07-g4-hypernuclei for the darkness ranking. `scripts/graphdet_specials.py` released.

## 2026-10-24 06:05 JST — Claude (e07-srv): intent — B' on v3_embed_nagara_dz1.5 ev0000-0019

Specials ranking (e07-g4-hypernuclei, output/specials_ranking.md): the multiplicity+darkness combination beats the shifted control on all 9 real events, while multiplicity did not help on the dz3.0 pseudo images. To see whether dz1.5 pseudo images behave like the real data, run B' (cell 6, 12 workers) on v3_embed_nagara_dz1.5 ev0000-0019 -> `results/sim_eval/v3_embed_nagara_dz1.5_bprime.csv` + `.done` (~2 h). Same 20 events as the dz3.0 run. Scratch script; no repo code changes.

## 2026-10-24 06:55 JST — Claude (e07-srv): intent — Method A on v14 synthetic (dz1.5)

Requested by e07-g4-hypernuclei. Method A (production / relaxed, z_best) on v14_synth_nagara_replay_dz1.5 and v14_synth_ibuki_replay_dz1.5 (10 ev each) -> `results/sim_eval/<ds>_methodA_{production,relaxed}.csv`. Runs alongside the dz1.5 B' job. Scratch scripts.

## 2026-10-24 06:58 JST — Claude (e07-srv): done — Method A on v14 synthetic (dz1.5)

Both v14 datasets finished (10 ev each); production ~880 candidates/view, relaxed ~950. dz1.5 B' still running (6/20 at this time).

## 2026-10-24 07:52 JST — Claude (e07-srv): done — B' on v3_embed_nagara_dz1.5 ev0000-0019

20 events, ~29k branch points/event; `.done` written. Ranking comparison with dz3.0 is with e07-g4-hypernuclei. No jobs running.

## 2026-10-26 14:55 JST — Claude (e07-srv): intent — point-cloud quality harness (pre-MATLAB segmentation)

User redirected: hypernuclear vertices aside; compare and develop the stages that build the point cloud for the graph detector (fog removal, binarisation, denoise, grid sampling), judged on point-cloud and track quality. Plan agreed with Codex (round 8). New file `scripts/eval_pointcloud.py` (owned by me): stage-wise ablation (Otsu only / +small-blob removal / +denoise off|legacy|threshold|classifier / sampling cell and skeleton) scored against e07-g4-hypernuclei pixel labels (`labels.npz`): hit purity vs radius with a shifted-position chance control, label-region coverage by class, per-track coverage and new gaps, cross-track mixed hits, duplicates, hits per graphdet region. Built on v14 now; real comparisons wait for v15 (dz 4.0) with grain-level truth requested from e07-g4-hypernuclei. No production code changes yet; outputs under `results/pointcloud_eval/`.

Note: the physical step is now ~4.0 um/slice (e07-g4-hypernuclei, layer-depth count). `module/graphdet/config.py` MATLAB_Z_SCALE (3.0/0.29) and the unused E07_Z_SCALE (1.5/0.29, comment "E07 is 1.5 um") are affected; changing them is left to the user.

## 2026-10-26 15:28 JST — Claude (e07-srv): progress — point-cloud harness on grain truth

`scripts/eval_pointcloud.py` now matches hits to e07-g4-hypernuclei `grains.npz` in 3-D. On the two dev events (partial v15, not for reporting) the production classifier denoise is worse than random thinning at the same budget, and a DoG grain detector (`dog3d`) gives higher purity and recall at ~60% of the budget, 10 s/view. On real views DoG hit counts match the synthetic, but long line-like tracks get few hits. Production export unchanged. Details in analysis-note.

## 2026-10-26 15:38 JST — Claude (e07-srv): intent — point-cloud variants on v15 tune and v15 embed

Run `scripts/eval_pointcloud.py` (all variants incl. new oriented line detector `ridge`/`ridge3d`/`dogridge`) on `v15_synth_tune_dz4` and `v15_embed_nagara_dz4` (10 events each) -> `results/pointcloud_eval/v15/`. Mechanics check only; decisive comparison on v16 per agreement with e07-g4-hypernuclei. Embed events: signal-grain recall with real background (purity not meaningful there).

## 2026-10-26 17:42 JST — Claude (e07-srv): intent — point-cloud variants on single_eval_dz4

`scripts/eval_pointcloud.py` (variants otsu, blob, classifier, otsu_rand, dog, dog3d, ridge, dogridge; with background-only control) on e07-g4-hypernuclei `single_eval_dz4` (80 events x 25 single tracks) -> `results/pointcloud_eval/single_dz4/`. Per-track recall then joined with `single_tracks.csv` (species, dip, length, dE/dx).

## 2026-10-26 19:55 JST — Claude (e07-srv): intent — Method A on v19_embed_nagara_dz4; point cloud on v19 synth

Requested by e07-g4-hypernuclei. Method A (production / relaxed, z_best) on `v19_embed_nagara_dz4` (100 events) -> `results/sim_eval/v19_embed_nagara_dz4_methodA_{production,relaxed}.csv`; dz3.6 to follow. B' on dz4 only, later at low priority (~10 h). Point-cloud evaluation on `v19_synth_tune_dz4` (tuning) next; `v19_synth_eval2_dz4` kept untouched until methods and thresholds are frozen.

## 2026-10-26 20:15 JST — Claude (e07-srv): intent — Method A on v19 background views (control)

Requested by e07-g4-hypernuclei. Method A (production / relaxed) on the source views of `v19_embed_nagara_dz4` (`output/background_views_v19_embed_nagara_dz4.csv`, 100 rows / 90 views) -> `results/sim_eval/v19_bgonly_nagara_dz4_methodA_{production,relaxed}.csv`.

## 2026-10-26 20:23 JST — Claude (e07-srv): intent — Method A on v19_embed_nagara_dz3.6

Requested by e07-g4-hypernuclei. Method A (production / relaxed) on `v19_embed_nagara_dz3.6` (100 events) -> `results/sim_eval/v19_embed_nagara_dz3.6_methodA_{production,relaxed}.csv`.

## 2026-10-26 20:33 JST — Claude (e07-srv): fix — GPU out-of-memory fallback missed AcceleratorError

`module/pipeline/finder.py` `_gpu_oom()` (owned by me for this change) caught only `torch.OutOfMemoryError`; when the shared card is full at context creation, torch raises `torch.AcceleratorError` instead and the Method A shard died (40 of 100 background-control events lost). It now returns both, so the existing CPU fallback (same numbers) runs. Same in `scripts/eval_pointcloud.py`. Rerunning the lost events.

## 2026-10-26 20:47 JST — Claude (e07-srv): done — Method A on v19 background views

All 100 events (90 views) after the AcceleratorError fix: `results/sim_eval/v19_bgonly_nagara_dz4_methodA_{production,relaxed}.csv`.

## 2026-10-26 20:50 JST — Claude (e07-srv): done — Method A on v19_embed_nagara_dz3.6

All 100 events: `results/sim_eval/v19_embed_nagara_dz3.6_methodA_{production,relaxed}.csv`.

## 2026-10-26 20:54 JST — Claude (e07-srv): intent — B' on v19_embed_nagara_dz4 (100 events)

Requested by e07-g4-hypernuclei. B' (cell 6, 12 workers) -> `results/sim_eval/v19_embed_nagara_dz4_bprime.csv`, `.done` at the end (~10 h). Point-cloud jobs will share the machine at low parallelism meanwhile.

## 2026-10-26 22:21 JST
Intent (Claude, fullscan): Method A on v20_embed_nagara_dz4 (peer request).
- Input: e07-g4-hypernuclei/data/images/v20_embed_nagara_dz4 (100 ev).
- Output: results/sim_eval/v20_embed_nagara_dz4_methodA_{production,
  relaxed}.csv. Same scratch scripts as v19; no repo code changes.
- Control: reuse v19_bgonly_nagara_dz4 (same views, same seed).
- Runs alongside B' on v19 dz4 (6 CPU workers).

## 2026-10-26 22:27 JST
Done (Claude, fullscan): two-grain toy for dog3d (Codex round 12).
- scripts/toy_twograin.py (new, owned by fullscan). Imports the sim
  repo's render/calibrate read-only under the alias "simmodule".
- Output: results/pointcloud_eval/toy_twograin/toy_twograin.csv.
- v19 optics: DoG response barely drops at +-1 slice, so dog3d z
  resolution is ~+-1 slice. Cross-grain suppression only within 3 px
  xy and 2 slices (near-vertical tracks, beam). Mean grain found 100%
  at K=2, 88% at K=3. K=2 proposed as primary, pending graphdet cost.
Next: graphdet stage 1/2 cost on tune events (after Method A v20).

## 2026-10-26 22:37 JST
Intent (Claude, fullscan): merge-aware metrics and dog3dz, tune set.
- scripts/eval_pointcloud.py (owned): new columns xrecall_<class>,
  close_frac/close_recall/close_xrecall (each hit credited to its
  nearest grain's track only), dz_abs_med/dz_bias/dz_n (isolated
  grains). New variant dog3dz (5-slice least-squares depth fit) and
  --dog-k. ridge_response/line_mask unchanged.
- Run: v19_synth_tune_dz4 (10 ev), K=3 {classifier, otsu_rand, dog3d,
  dog3dz} and K=2 {dog3d, dog3dz}.
- Output: results/pointcloud_eval/v19_tune_x/ (tags k3_, k2_).

## 2026-10-26 22:41 JST
Done (Claude, fullscan): Method A on v20_embed_nagara_dz4, 100 events.
- results/sim_eval/v20_embed_nagara_dz4_methodA_production.csv (77023
  rows), ..._relaxed.csv (89854 rows). v19 had 77052 / 89862.
- Control: v19_bgonly_nagara_dz4_methodA_*.csv (same views).

## 2026-10-26 22:42 JST
Intent (Claude, fullscan): graphdet stage 1/2 cost and track quality.
- scripts/graphdet_pointcloud.py (new, owned). Input: v19_synth_tune_dz4
  ev0000-ev0002; variants production (classifier export), dog3d K=2/3,
  dog3dz K=2. 8 workers, one variant at a time (B' uses 12).
- Output: results/pointcloud_eval/graphdet/.

## 2026-10-26 22:53 JST
Done (Claude, fullscan): scripts/grain_depth_profile.py (new, owned;
peer request). Truth-free depth profile of isolated dog3d grains.
- Real eval background V00001531: FWHM median 7.2 slices, profile at
  +-4 slices 0.69/0.74. v19_synth_tune ev0000: 5.6 slices, 0.32/0.35.
  Real grains fade more slowly than synthetic, not faster. Caveat:
  near-vertical beam tracks also pass the isolation test.

## 2026-10-26 23:35 JST
Done (Claude, fullscan): tune-set metrics and graphdet stage 1/2 cost.
- results/pointcloud_eval/v19_tune_x/, results/pointcloud_eval/graphdet/.
- Per view: production ~190 s total, dog3dz K=2 ~220 s. Background
  tracks >=50% reconstructed: production 0.002, dog3dz K=2 0.74.
- Provisional: primary dog3dz K=2, sensitivity dog3d K=3; recheck on
  v21 optics. Details in analysis-note.md.

## 2026-10-26 23:42 JST
Intent (Claude, fullscan): Codex round 13 scoring fixes, tune rerun.
- eval_pointcloud.py: depth error now grain-side on a common isolated
  set (dz_abs_med/p90, dz_bias, dz_miss); fit_flat/fit_clip for dog3dz.
- graphdet_pointcloud.py: --z-um (detector z scale), per-track rec_best
  (single best polyline), polyline main_frac, fake count/length, peak
  RSS of the whole process tree.
- Runs: eval on v19_synth_tune_dz4 (10 ev) -> results/pointcloud_eval/
  v19_tune_x2/; graphdet on ev0000-0002, {production, dog3d K3/K2,
  dog3dz K2} x {z 3.0 (MATLAB), 3.8 um} -> results/pointcloud_eval/
  graphdet2/. Timing is contended by B'; clean timing after B'.

## 2026-10-27 02:34 JST Note (Claude, fullscan): plan after peer depth-width study
- Peer (sim): no v21; v19 stays the model for tune/eval. Synthetic
  isolated grains have ~15% narrower depth response than real, so
  synthetic z precision (dz_abs_med/p90) is optimistic; real views have
  fewer compact isolated grains (26% vs 43%).
- Consequence for fullscan: no retune of FIT_HALF or z-merge for v21.
  v19 tune stays the development set; v19_synth_eval2_dz4 is evaluated
  once, after the acceptance criteria are written down, and is then the
  held-out result. z precision from synth is reported as an optimistic
  bound; the real-vs-synth depth FWHM gap is quoted next to it.
- Housekeeping: the single_dz4 redo copy job stalled on an interactive
  cp prompt; the files were already identical, the cp was killed.

## 2026-10-27 02:54 JST Done + intent (Claude, fullscan): round-13 reruns, graphdet fix
- Done: v19 tune rerun -> results/pointcloud_eval/v19_tune_x2/;
  graphdet ev0000-0002 x {production, dog3d K3/K2, dog3dz K2} x z
  {3.0, 3.8} -> results/pointcloud_eval/graphdet2/ (contended timing).
  Summary in analysis-note.md (this time).
- Bug: graphdet_pointcloud polyline purity treated negative instance ids
  (background tracks) as 'no owner', so fake_frac/main_frac in
  graphdet2 are invalid (track-side rec_frac/rec_best are fine). Fixed,
  vectorised, polylines now saved (_polys.npz); quality()/load_polys()
  for re-scoring. eval_pointcloud is unaffected.
- Intent: after B' (v19_embed_nagara_dz4) finishes, rerun the same 24
  graphdet cases sequentially without contention ->
  results/pointcloud_eval/graphdet3/ (clean total_s / RSS, fake and
  main_frac). Owned: scripts/graphdet_pointcloud.py,
  scripts/eval_pointcloud.py, results/pointcloud_eval/{v19_tune_x2,
  graphdet2,graphdet3}/.

## 2026-10-27 03:02 JST Done + intent (Claude, fullscan): Codex round 14, scorer v3
- Codex 14: agrees dog3dz K2 primary; fix the scorer before freezing.
  rec_best split support between overlapping polylines (nearest-only
  assignment) -> now each polyline's grains counted independently
  (sparse pair search). Added run_best, n_frag50, main_share_all
  (length-weighted, unmatched in the denominator), {bg,sig}_cov_grains.
  graphdet3 (queued after B') picks this up; polylines are saved.
- Checks on tune: dog3dz z shift moves hits out of the +-1 slice box
  for 2.5% of hits and in for 6.9% (all tracks; signal 45 out / 92 in)
  - the lost short track is a real but net-minority failure mode.
  Background tracks are fragmented at stage-2 output (dog3d K3 ev0000:
  polyline length median 20 um, n_frag50 median 13; 4 pieces even for
  20-50 grain tracks); production comparison comes with graphdet3.
- Plan per Codex: criteria at z 3.8 (3.0 as compatibility); graph
  detector for dog3dz K2 and production on all 10 eval2 views, dog3d K3
  on 3. Owned files unchanged from the previous entry.

## 2026-10-27 06:13 JST Done (Claude, fullscan): B' on v19_embed_nagara_dz4
- results/sim_eval/v19_embed_nagara_dz4_bprime.csv (100 events) and .done written; peer notified. graphdet3 now runs without contention.

## 2026-10-27 06:42 JST Intent (Claude, fullscan): B' on v20_embed_nagara_dz4 (peer request)
- Queued after graphdet3 (24 cases), nice 19. Input: e07-g4-hypernuclei/data/images/v20_embed_nagara_dz4 (100 ev). Output: results/sim_eval/v20_embed_nagara_dz4_bprime.csv + .done. ~7 min/event, ~12 h.

## 2026-10-27 11:26 JST Note (Claude, fullscan): queue fix
- The wait-for-B' loops (pgrep -f on the B' command) matched their own shell, so graphdet3 never started. Killed; graphdet3 started directly (~2 h, results/pointcloud_eval/graphdet3/). v20 B' still queued behind it (nice 19, same sim_bprime.py as v19, cell 6).

## 2026-10-27 11:30 JST Done (Claude, fullscan): sim figure in README (user request)
- scripts/sim_figure.py -> docs/figures/sim_to_image.png: v19_embed_nagara_dz4/ev0021, Geant4 tracks (plane, side), grains, grains through the optics (Renderer, v19 model), dataset slice on the real background, min projection. Reads the sim repo only.

## 2026-10-27 12:54 JST Intent (Claude, fullscan): v19 eval2, criteria frozen
- Criteria frozen in analysis-note.md (this time) before any eval2 output.
- Runs on e07-g4-hypernuclei/data/images/v19_synth_eval2_dz4 (10 ev): eval_pointcloud {classifier, otsu_rand, dog3d, dog3dz} K3 and {dog3d, dog3dz} K2 -> results/pointcloud_eval/v19_eval2/; graphdet z 3.8 {production, dog3dz K2} x 10 ev, {dog3d K3} x 3 ev, z 3.0 {production, dog3dz K2} x 3 ev -> results/pointcloud_eval/graphdet_eval2/. Runs alongside v20 B' (nice 19).

## 2026-10-27 15:30 JST Done (Claude, fullscan): v19 eval2 verdict
- Frozen criteria applied once to v19_synth_eval2_dz4 (10 views); eval2 is now spent. Details in analysis-note.md.
- dog3dz K2 passes (a) bg xrecall >= 4.17x classifier, per-hit >= 1.66x otsu_rand; (b) stratum loss below classifier (short 0.474), signal total loss 3 vs 22; (e) dz p90 <= classifier 10/10, |bias| <= 0.017. On grains both detect, |dz| median 0.76 -> 0.60 but p90 equal (1.36): the p90 gain comes from which grains are found.
- Fails (c) fake length per view, median ratio 2.91 vs production (limit 2; ~3x in the 8 sparse views), and (d) max total_s ratio 2.53 (limit 2.5; median 1.79, v20 B' running alongside). The rest of (c) passes: sig best_good 0.419 vs 0.174, bg good 0.743 vs 0.002, main_share_all 10/10, main_frac -0.06.
- My error: the freeze note's "fake length 1.54x on tune" was the pooled ratio; per-view median on tune was already 3.18. Criteria not rewritten; counted as fail.
- Conclusion: better point cloud, but no production replacement. Next: tune stage-2 fake suppression for a denser cloud on v19 tune; a fresh unused set will be needed for the next held-out check.
