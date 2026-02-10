# ISSUE-0076 — Job FSM (pending→running→completed/failed/dlq)

This high-level TODO is already implemented by earlier work:
- Job status machine + DLQ behavior: `backend/app/jobs/model.py`
- Backoff utilities: `backend/app/jobs/backoff.py`
- Tests: `backend/tests/test_job_fsm.py`

Verification:
- `pwsh -NoProfile -File scripts/test_backend.ps1` (PASS)

Notes:
- Superseded by `ISSUE-0018`.

