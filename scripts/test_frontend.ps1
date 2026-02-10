$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

if (-not (Test-Path "frontend\\package.json")) {
  Write-Host "[test_frontend] frontend/package.json not found -> skip"
  exit 0
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  throw "npm not found but frontend/package.json exists"
}

Write-Host "[test_frontend] npm -C frontend run lint (if present)"
try { npm -C frontend run lint } catch { Write-Host "[test_frontend] lint missing or failed: $($_.Exception.Message)"; throw }

Write-Host "[test_frontend] npm -C frontend run typecheck (if present)"
try { npm -C frontend run typecheck } catch { Write-Host "[test_frontend] typecheck missing or failed: $($_.Exception.Message)"; throw }

Write-Host "[test_frontend] npm -C frontend test (if present)"
try { npm -C frontend test } catch { Write-Host "[test_frontend] test missing or failed: $($_.Exception.Message)"; throw }

Write-Host "[test_frontend] npm -C frontend run build (if present)"
try { npm -C frontend run build } catch { Write-Host "[test_frontend] build missing or failed: $($_.Exception.Message)"; throw }

Write-Host "[test_frontend] OK"

