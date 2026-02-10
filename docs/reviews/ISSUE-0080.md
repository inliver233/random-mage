# ISSUE-0080 — Field encryption module (Fernet/AES-GCM)

This high-level TODO is already implemented by earlier work:
- Field encryption + masking helper (Fernet): `backend/app/core/crypto.py`
- Tests: `backend/tests/test_crypto.py`

Verification:
- `pwsh -NoProfile -File scripts/test_backend.ps1` (PASS)

Notes:
- Superseded by `ISSUE-0008`.

