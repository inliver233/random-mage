# ISSUE-0077 — Backoff calculation

This high-level TODO is already implemented by earlier work:
- Backoff utilities: `backend/app/jobs/backoff.py`
- Tests (covers backoff behavior): `backend/tests/test_job_fsm.py`

Verification:
- `pwsh -NoProfile -File scripts/test_backend.ps1` (PASS)

Notes:
- Superseded by `ISSUE-0018`.

