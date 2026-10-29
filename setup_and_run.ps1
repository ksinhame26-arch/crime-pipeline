# One-click setup: start Docker stack, create venv, install deps, run pipeline once.
# Output is also saved to setup_log.txt in this folder.
$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot
Start-Transcript -Path "$PSScriptRoot\setup_log.txt" -Force | Out-Null

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

Step "1. Checking Docker"
$dockerBins = @("$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin", "C:\Program Files\Docker\Docker\resources\bin")
foreach ($b in $dockerBins) { if ((Test-Path $b) -and ($env:Path -notlike "*$b*")) { $env:Path = "$b;$env:Path" } }
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker engine not running - starting Docker Desktop..."
    $dd = @("$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe", "C:\Program Files\Docker\Docker\Docker Desktop.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($dd) { Start-Process $dd } else { Write-Host "Docker Desktop.exe not found" }
    $ok = $false
    for ($i = 0; $i -lt 36; $i++) {
        Start-Sleep -Seconds 5
        docker info *> $null
        if ($LASTEXITCODE -eq 0) { $ok = $true; break }
        Write-Host "  waiting for Docker engine... ($(($i+1)*5)s)"
    }
    if (-not $ok) {
        Write-Host "RESULT: DOCKER_NOT_READY - open Docker Desktop, wait for 'Engine running' (restart PC if it asks), then run this again." -ForegroundColor Red
        Stop-Transcript | Out-Null; Read-Host "Press Enter to close"; exit 1
    }
}
docker --version
docker compose version

Step "2. Starting PostgreSQL, pgAdmin, Metabase (first time downloads ~1.5 GB)"
docker compose up -d
if ($LASTEXITCODE -ne 0) { Write-Host "RESULT: COMPOSE_FAILED" -ForegroundColor Red; Stop-Transcript | Out-Null; Read-Host "Press Enter to close"; exit 1 }

Write-Host "Waiting for postgres_cpd and prefect_server to be healthy..."
for ($i = 0; $i -lt 60; $i++) {
    $h = docker inspect -f "{{.State.Health.Status}}" postgres_cpd 2>$null
    $p = docker inspect -f "{{.State.Health.Status}}" prefect_server 2>$null
    if ($h -eq "healthy" -and $p -eq "healthy") { break }
    Start-Sleep -Seconds 3
}
docker compose ps 2>&1 | Out-Host

Step "3. Python virtual environment + packages"
if (-not (Test-Path ".venv")) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { python -m venv .venv }
}
$py = "$PSScriptRoot\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip -q
& $py -m pip install -r etl\requirements.txt -q
if ($LASTEXITCODE -ne 0) { Write-Host "RESULT: PIP_FAILED" -ForegroundColor Red; Stop-Transcript | Out-Null; Read-Host "Press Enter to close"; exit 1 }

Step "4. Testing Socrata API"
Set-Location etl
& $py test_api.py 2>&1 | Out-Host

Step "5. Running the ETL pipeline once"
& $py etl_pipeline.py --once 2>&1 | Out-Host
$etl = $LASTEXITCODE
Set-Location ..

Step "6. Checking the database"
docker exec postgres_cpd psql -U cpd_user -d cpd_db -c "SELECT COUNT(*) AS rows, MIN(date_time) AS first_incident, MAX(date_time) AS last_incident FROM cpd_incidents;" 2>&1 | Out-Host
docker exec postgres_cpd psql -U cpd_user -d cpd_db -c "SELECT type, COUNT(*) FROM cpd_incidents GROUP BY type ORDER BY 2 DESC LIMIT 5;" 2>&1 | Out-Host

if ($etl -eq 0) {
    Write-Host "`nRESULT: SUCCESS - opening Metabase at http://localhost:3000 (first start can take ~1 minute)" -ForegroundColor Green
    Start-Process "http://localhost:3000"
} else {
    Write-Host "`nRESULT: ETL_FAILED - see errors above" -ForegroundColor Red
}
Stop-Transcript | Out-Null
Read-Host "Press Enter to close"
