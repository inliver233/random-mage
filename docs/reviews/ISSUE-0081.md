# ISSUE-0081 — refresh_token write-only (API never echoes)

This requirement is enforced by more granular issues:
- Encryption + masking helpers: `ISSUE-0008`
- Token API endpoints must never return plaintext `refresh_token`: `ISSUE-0154` / `ISSUE-0155` / `ISSUE-0156` / `ISSUE-0157`
- Security gate tests (no secret echo): `ISSUE-0240`

Verification:
- `pwsh -NoProfile -File scripts/test_backend.ps1` (PASS)

Notes:
- This ISSUE is a high-level TODO; progress is tracked in the superseding issues above.

