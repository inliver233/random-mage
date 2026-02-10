# ISSUE-0098 — rendezvous hashing primary 绑定（TEST）

This is a high-level TODO from `TODO-全量Issue拆分.md` and is tracked by more granular issues:

- Primary binding computation is part of bindings recompute:
  - `ISSUE-0167`: `POST /admin/api/bindings/recompute` (implements rendezvous hashing + persists primary bindings)

Verification:
- `py -3.11 .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-02-10_15-43-12-new-pixiv-api-delivery.csv` (PASS)

Notes:
- This ISSUE is redundant; progress is tracked in the superseding issue above.

