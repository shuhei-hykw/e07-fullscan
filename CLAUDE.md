# Coding Rules

## Language
- Always respond in Japanese

## Git commits
- Never add `Co-Authored-By` trailers (or any AI co-authorship attribution
  such as "Generated with Claude Code") to commit messages or PR bodies.

## Package structure
- Main package: module (renamed from e07fullscan 2026-05-30; not imported
  externally, so a generic import name is acceptable)
- Subpackages: io, tracking, analyze, merge, clustering, server, utils,
  diagnostics
- Shared module: preprocess (branch-neutral fog/Otsu/noise, used by tracking
  and server)

## Style
- Indentation: 2 spaces (never tabs)
- In-code comments: English only

## Error handling
- Include essential error guards, but keep code concise and minimal

## Formatting
- Line length: 79 characters max
- Avoid magic numbers; always assign named constants

## Documentation
- Always update and review ANALYSIS.md and README.md in English
- Always update ANALYSIS_ja.md in Japanese (mirrors ANALYSIS.md)
- ANALYSIS.md / ANALYSIS_ja.md are **chronological development diaries**
  (lab notebook style). Record not just results but also discussions,
  hypotheses, dead ends, and the reasoning behind decisions.
  Each entry is dated and appended at the bottom; never reorganise or remove
  existing entries. New entries go under `## YYYY-MM-DD — <title>`.
- For every work session recorded in ANALYSIS.md (every dated entry, not just
  major milestones), also create a corresponding entry in the Notion
  **image-pre-processing DB** (ID: `7849f15c90f643eb97a471342e02e42d`).
  Use the Notion MCP server (`notion` in ~/.claude/.mcp.json) when available,
  or `notion-client` Python library as fallback.
  Entry schema: Title=date, Date=YYYY-MM-DD, Status=Done/In Progress,
  Type=Analysis/Experiment/Commit, Summary=one-line memo.
  Page body: ## What I did / ## Results / ## Next steps sections.

## Agent Coordination
- Always check both `discussion.md` and `discussion_ja.md` before starting
  repository work, before editing shared files, and before final reporting.
- Treat new entries in those files as active coordination state from the
  other agent or the user.
- New Markdown log entries should include both date and time, preferably in
  `YYYY-MM-DD HH:MM JST` form. Do not rewrite older date-only entries just to
  add times.
- Keep both discussion files append-only. Never reorganise or remove existing
  entries.
- Before editing files that another agent lists as active, record the intent
  in both discussion files and avoid the edit unless the user explicitly asks
  for it or the coordination note makes the ownership clear.
- When launching jobs, generating outputs, or changing scripts, record the
  intended input files, output files/directories, and owned files in the
  discussion logs first.
- If a conclusion or result matters beyond short-term coordination, also
  append it to `ANALYSIS.md` and `ANALYSIS_ja.md` as dated diary entries.
