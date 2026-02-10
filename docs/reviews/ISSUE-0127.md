# ISSUE-0127 — Jobs（list/detail/retry）（UI）

This is a high-level TODO from `TODO-全量Issue拆分.md` and is tracked by more granular issues:

- UI:
  - `ISSUE-0193`: UI page `Jobs` (`/admin/jobs`)
- API:
  - `ISSUE-0172`: `GET /admin/api/jobs`
  - `ISSUE-0173`: `POST /admin/api/jobs/{id}/retry|cancel|move-to-dlq`

Verification:
- `py -3.11 .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-02-10_15-43-12-new-pixiv-api-delivery.csv` (PASS)

Notes:
- This ISSUE is redundant; progress is tracked in the superseding issues above.

