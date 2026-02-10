# Load Testing / Benchmarking

This project includes a small, **zero-dependency** (no k6/locust required) benchmark script to sanity-check `/random` throughput and latency.

## In-process benchmark (recommended for quick checks)

Runs the FastAPI app in-process via `httpx.ASGITransport`, seeds a temporary SQLite DB with synthetic images, then fires concurrent requests.

PowerShell:

```powershell
cd E:\pixiv-download-修改版本\new-pixiv-api实现
py -3.11 scripts/perf/bench_random_asgi.py --requests 2000 --concurrency 100 --seed-images 20000 --output docs/qa/reports/random_bench.json
```

Notes:
- This measures **application + SQLite** only (no real network / CDN / upstream image download).
- Endpoint defaults to `"/random?format=json&attempts=1"`. Override via `--endpoint`.

## Interpreting the report

The JSON report includes:
- request counts: `ok / no_match / other_error`
- latency percentiles: `p50/p90/p99` (seconds)
- throughput: `rps` (requests per second)

## Optional: real external load tools (k6/locust)

For production-like tests (real HTTP, reverse proxy, Docker, etc.), use k6/locust against a running deployment. Keep `/random` in `format=json` or `redirect=1` if you want to avoid upstream image traffic during load.

