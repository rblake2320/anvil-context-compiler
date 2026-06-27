[CmdletBinding()]
param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8787,
  [string]$ApiKey = "change-me-local-dev-key"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$activate = Join-Path $repo ".venv\Scripts\Activate.ps1"
if (Test-Path $activate) { . $activate }

$env:ANVIL_API_KEY = $ApiKey
anvil-compile serve --host $HostName --port $Port
