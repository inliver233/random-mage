# ISSUE-0075 — Jobs claim algorithm + lock TTL

This high-level TODO is already implemented by earlier work:
- Claim algorithm (SQLite `UPDATE..RETURNING`) + lock TTL: `backend/app/jobs/claim.py`
- Tests (multi worker / no double-claim / TTL reclaim): `backend/tests/test_jobs_claim.py`

Verification:
- `pwsh -NoProfile -File scripts/test_backend.ps1` (PASS)

Notes:
- Superseded by `ISSUE-0017`.

