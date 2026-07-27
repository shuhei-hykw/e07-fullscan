# Coding Rules

claude --resume d7a92435-fa77-40ec-a090-1287be7af59f # kekcc
claude --resume 702bbb20-294e-43e3-969e-f2c19dd02c06 # macos

## Language
- Always respond in Japanese

## Git commits
- Never add `Co-Authored-By` trailers (or any AI co-authorship attribution
  such as "Generated with Claude Code") to commit messages or PR bodies.

## Package structure
- Main package: module (renamed from e07fullscan 2026-05-30; not imported
  externally, so a generic import name is acceptable)
- Subpackages: io, tracking, analyze, merge, clustering, server, utils,
  diagnostics, review
- Shared module: preprocess (branch-neutral fog/Otsu/noise, used by tracking
  and server)
- Monitor/status helpers: module/pipeline_status.py (pipeline overview, used
  by monitor --pipeline and the deprecated scripts/status.py wrapper);
  module/utils/job_monitor.py (live-job monitor body for scripts/monitor.py)

## Style
- Indentation: 2 spaces (never tabs)
- In-code comments: English only

## Error handling
- Include essential error guards, but keep code concise and minimal

## Formatting
- Line length: 79 characters max
- Avoid magic numbers; always assign named constants

## Documentation
- **Read `STATUS.md` first** when starting a session. It is the
  current-state summary: method status, current best numbers with their
  measurement conditions, authoritative parameter values, active
  constraints, next candidates.
- `STATUS.md` is **overwritten in place, never appended** (history comes
  free from `git log -p STATUS.md`). Keep it short. **Update it in the
  same commit as any change that invalidates it** — a stale STATUS.md is
  worse than none, since sessions act on it directly.
- `analysis-note.md` and `STATUS.md` have different jobs and both stay:
  the note is append-only history (including superseded conclusions and
  dead ends), STATUS.md is only what is true now. If they disagree, the
  newest analysis-note.md entry wins.
- Always update and review README.md in English.
- `analysis-note.md` is the single development diary (lab notebook style,
  in Japanese; replaced ANALYSIS.md / ANALYSIS_ja.md on 2026-07-11).
  Record not just results but also discussions, hypotheses, dead ends, and
  the reasoning behind decisions.
- Entries are **reverse-chronological** (newest at the top of the log
  section). Insert new entries directly below the
  `## 開発ログ（最新が上）` heading, under
  `## YYYY-MM-DD HH:MM JST — <title>`. Never reorganise or remove existing
  entries; older date-only headers stay as they are.
- Notion is no longer used (retired 2026-07-11).

## Agent Coordination
- Always check both `discussion.md` and `discussion_ja.md` before starting
  repository work, before editing shared files, and before final reporting.
- Treat new entries in those files as active coordination state from the
  other agent or the user.
- New Markdown log entries should include both date and time, preferably in
  `YYYY-MM-DD HH:MM JST` form. Do not rewrite older date-only entries just to
  add times.
- Keep both discussion files append-only. Never reorganise or remove existing
  entries. Exception: when they grow unwieldy, old entries may be split into
  a dated archive file (`discussion_archive_*.md`) **verbatim** and only on
  explicit user request — done once on 2026-07-27 for pre-2026-07-11
  entries. Never edit or drop content in the process.
- Before editing files that another agent lists as active, record the intent
  in both discussion files and avoid the edit unless the user explicitly asks
  for it or the coordination note makes the ownership clear.
- When launching jobs, generating outputs, or changing scripts, record the
  intended input files, output files/directories, and owned files in the
  discussion logs first.
- If a conclusion or result matters beyond short-term coordination, also
  record it in `analysis-note.md` as a dated diary entry (newest first).
