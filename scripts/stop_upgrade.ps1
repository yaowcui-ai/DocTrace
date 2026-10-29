$ErrorActionPreference = 'Stop'
$projectDirectory = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location -LiteralPath $projectDirectory
try {
    # Explicit project files; stop retains containers, indexes and database volumes.
    & docker compose --env-file runtime/upgrade/.env -f deploy/compose.upgrade.yml --profile managed-worker stop
    if ($LASTEXITCODE -ne 0) { throw 'Upgrade stop failed.' }
    & docker compose --env-file runtime/upgrade/.env -f deploy/compose.hr-managed.yml --profile managed stop
    if ($LASTEXITCODE -ne 0) { throw 'Managed LightRAG stop failed.' }
    Write-Host 'Stopped only upgrade services. Database volumes and managed indexes retained.'
} finally { Pop-Location }
