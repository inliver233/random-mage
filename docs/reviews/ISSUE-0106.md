# ISSUE-0106 — hydrate job handler（Jobs UI 可看到成功/失败）

This is a high-level TODO from `TODO-全量Issue拆分.md` and is tracked by more granular issues:

- Job handler:
  - `ISSUE-0177`: Job handler `hydrate_metadata`
- Jobs API + UI visibility:
  - `ISSUE-0172`: `GET /admin/api/jobs`
  - `ISSUE-0193`: UI page `Jobs` (`/admin/jobs`)

Verification:
- `py -3.11 .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-02-10_15-43-12-new-pixiv-api-delivery.csv` (PASS)

Notes:
- This ISSUE is redundant; progress is tracked in the superseding issues above.

