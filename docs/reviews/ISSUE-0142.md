# ISSUE-0142 — API: GET `/i/{image_id}.{ext}`

## Contract checklist

- Path: `GET /i/{image_id}.{ext}`
- Behavior:
  - Streams upstream bytes (Pixiv original URL) via `httpx` streaming.
  - Supports `Range` passthrough (`206`).
  - Sets long-cache header: `Cache-Control: public, max-age=31536000, immutable`.
  - Validates `ext` against allowed image extensions.
  - Returns `404` when `image_id` missing or `ext` mismatch.
  - Always echoes `X-Request-Id` (via request-id middleware).

## Evidence

- Implementation: `backend/app/api/public/images.py`
- Tests:
  - `backend/tests/test_image_proxy.py`
- Verification command:
  - `pwsh -NoProfile -File scripts/test_backend.ps1`

