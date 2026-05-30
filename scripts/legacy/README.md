# Legacy ΛΛ-pair scripts

Superseded on 2026-05-14 when the analysis switched from requiring a
primary+secondary vertex **pair** to detecting **individual** reaction
vertices directly (see ANALYSIS.md). Kept here for provenance and comparison —
they produced the historical ΛΛ pair catalogs and the KISO cross-view result.
They are not part of the current individual-vertex pipeline.

- `find_pairs.py` — build intra-view ΛΛ pair catalog (uses
  `module.clustering.find_vertex_pairs`)
- `find_crossview_pairs.py` — build cross-view pair catalog
- `filter_pairs_by_track.py`, `filter_xview_pairs.py` — connecting-track
  filters on pair candidates
- `annotate_pairs.py` — annotate pair candidates with connecting-track stats
- `crop_pairs.py` — render image crops for pair candidates

Run from the repository root with `PYTHONPATH=.` (paths resolve to the repo
root via `parents[2]`, since these now live one directory deeper).
