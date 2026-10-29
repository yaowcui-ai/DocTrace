param([switch]$NoBuild)
$ErrorActionPreference = 'Stop'
$projectDirectory = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location -LiteralPath $projectDirectory
try {
    if (!(Test-Path -LiteralPath 'runtime/upgrade/.env' -PathType Leaf)) { throw 'Run scripts/init_upgrade_config.py and configure supplier credentials first.' }
    if (!(Test-Path -LiteralPath 'runtime/upgrade/managed-lightrag.env' -PathType Leaf)) { throw 'Run scripts/init_managed_config.py first.' }
    & docker info --format '{{.ServerVersion}}'
    if ($LASTEXITCODE -ne 0) { throw 'Docker engine unavailable. Start Docker Desktop first.' }
    & docker compose --env-file runtime/upgrade/.env -f deploy/compose.hr-managed.yml --profile managed up -d
    if ($LASTEXITCODE -ne 0) { throw 'Managed LightRAG startup failed.' }
    [string[]]$buildArguments = if ($NoBuild) { '--no-build' } else { '--build' }
    & docker compose --env-file runtime/upgrade/.env -f deploy/compose.upgrade.yml --profile managed-worker up -d @buildArguments
    if ($LASTEXITCODE -ne 0) { throw 'Upgrade application startup failed.' }
    Write-Host 'Workspace: http://127.0.0.1:8005/workspace/'
    Write-Host 'Frozen corpus questions also require the existing 9624 service; managed questions use 9631.'
} finally { Pop-Location }
