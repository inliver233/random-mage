# ISSUE-0094 — 健康评分与过滤（random/hydrate 只用健康 proxy）

This is a high-level TODO from `TODO-全量Issue拆分.md` and is tracked by more granular issues:

- Probe & persistence (latency/ok/fail/blacklist timestamps):
  - `ISSUE-0179`: Job handler `proxy_probe`
- Selection & failover (only use healthy proxies in outbound paths):
  - `ISSUE-0101`: failover（proxy_connect/proxy_auth → override；rate_limit → token backoff）
- API/UI visibility (health fields surfaced for operations):
  - `ISSUE-0158`: `GET /admin/api/proxies/endpoints`

Verification:
- `py -3.11 .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-02-10_15-43-12-new-pixiv-api-delivery.csv` (PASS)

Notes:
- This ISSUE is redundant; progress is tracked in the superseding issues above.

