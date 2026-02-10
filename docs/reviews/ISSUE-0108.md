# ISSUE-0108 — opportunistic hydrate（random 命中缺元信息时入队）

This is a high-level TODO from `TODO-全量Issue拆分.md`.

Implementation is tracked by the following more granular issues:

- Enqueue behavior from `/random` when metadata is missing:
  - `ISSUE-0242`: Backend: opportunistic hydrate enqueue from `/random`
- Metrics visibility:
  - `ISSUE-0243`: Metric: `random_opportunistic_hydrate_enqueued_total`

Verification:
- `py -3.11 .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-02-10_15-43-12-new-pixiv-api-delivery.csv` (PASS)

Notes:
- This ISSUE is redundant; progress is tracked in the superseding issues above.

