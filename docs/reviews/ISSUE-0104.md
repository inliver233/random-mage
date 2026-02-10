# ISSUE-0104 — normalize：tags(name/translated_name) 去重

This is a high-level TODO from `TODO-全量Issue拆分.md` and is tracked by more granular issues:

- Tag normalization/dedup is implemented as part of metadata hydration:
  - `ISSUE-0177`: Job handler `hydrate_metadata`

Verification:
- `py -3.11 .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-02-10_15-43-12-new-pixiv-api-delivery.csv` (PASS)

Notes:
- This ISSUE is redundant; progress is tracked in the superseding issue above.

