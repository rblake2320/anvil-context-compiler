[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Invoke-NativeChecked {
  param(
    [Parameter(Mandatory = $true)][string]$Label,
    [Parameter(Mandatory = $true)][scriptblock]$Command
  )
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "$Label failed with exit code $LASTEXITCODE"
  }
}

$activate = Join-Path $repo ".venv\Scripts\Activate.ps1"
if (Test-Path $activate) { . $activate }

Invoke-NativeChecked "unit tests" { python -m unittest discover -s tests }
Invoke-NativeChecked "CLI smoke compile" { anvil compile --request "Build a minimal context compiler test" --context-file .\examples\sample_context.md --tool-file .\examples\tools.json --out .\.anvil\smoke_plan.json --prompt-out .\.anvil\smoke_prompt.txt }
Write-Host "ANVIL smoke test complete." -ForegroundColor Green
