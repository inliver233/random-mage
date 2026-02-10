# ISSUE-0107 — backfill run（hydration_runs）创建/暂停/恢复/取消（UI）

This is a high-level TODO from `TODO-全量Issue拆分.md` and is tracked by more granular issues:

- API:
  - `ISSUE-0170`: `POST /admin/api/hydration-runs`
  - `ISSUE-0171`: `POST /admin/api/hydration-runs/{id}/pause|resume|cancel`
- UI visibility/control:
  - `ISSUE-0193`: UI page `Jobs` (`/admin/jobs`) — run control is represented via jobs & run records

Verification:
- `py -3.11 .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-02-10_15-43-12-new-pixiv-api-delivery.csv` (PASS)

Notes:
- This ISSUE is redundant; progress is tracked in the superseding issues above.

