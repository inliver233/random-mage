# ISSUE-0100 — override TTL（TEST + UI 显示倒计时）

This is a high-level TODO from `TODO-全量Issue拆分.md` and is tracked by more granular issues:

- API:
  - `ISSUE-0168`: `POST /admin/api/bindings/{id}/override` (ttl_ms)
  - `ISSUE-0169`: `POST /admin/api/bindings/{id}/clear-override`
- UI:
  - `ISSUE-0192`: UI page `Bindings` (`/admin/bindings`) — shows override state/TTL

Verification:
- `py -3.11 .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-02-10_15-43-12-new-pixiv-api-delivery.csv` (PASS)

Notes:
- This ISSUE is redundant; progress is tracked in the superseding issues above.

