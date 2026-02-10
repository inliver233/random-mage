# ISSUE-0078 — Jobs API (list/detail/retry/cancel/move-to-dlq)

This item is a high-level TODO from `TODO-全量Issue拆分.md` and is tracked by more granular API issues:
- `ISSUE-0172`: `GET /admin/api/jobs?status=&type=&cursor=`
- `ISSUE-0173`: `POST /admin/api/jobs/{id}/retry|cancel|move-to-dlq`

Verification:
- `pwsh -NoProfile -File scripts/test_backend.ps1` (PASS)

Notes:
- This ISSUE is redundant; progress is tracked in the superseding issues above.

