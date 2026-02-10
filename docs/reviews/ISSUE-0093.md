# ISSUE-0093 — proxy_probe job（API+DB 更新 latency）

This is a high-level TODO from `TODO-全量Issue拆分.md` and is tracked by more granular issues:

- API:
  - `ISSUE-0161`: `POST /admin/api/proxies/probe`
- Job:
  - `ISSUE-0179`: Job handler `proxy_probe`
- Metrics:
  - `ISSUE-0233`: `proxy_probe_latency_ms`
- UI:
  - `ISSUE-0205`: UI action `探测健康（入队）`

Verification:
- `py -3.11 .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-02-10_15-43-12-new-pixiv-api-delivery.csv` (PASS)

Notes:
- This ISSUE is redundant; progress is tracked in the superseding issues above.

