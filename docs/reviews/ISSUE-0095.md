# ISSUE-0095 — blacklist 策略（失败阈值→blacklisted_until）

This is a high-level TODO from `TODO-全量Issue拆分.md` and is tracked by more granular issues:

- Blacklist persistence is implemented as part of proxy health probing:
  - `ISSUE-0179`: Job handler `proxy_probe` (updates `blacklisted_until` based on failures)

Verification:
- `py -3.11 .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-02-10_15-43-12-new-pixiv-api-delivery.csv` (PASS)

Notes:
- This ISSUE is redundant; progress is tracked in the superseding issue above.

