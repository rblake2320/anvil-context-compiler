[CmdletBinding()]
param(
  [string]$Python = "py -3.12",
  [switch]$Force
)

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

if ($Force -and (Test-Path ".venv")) {
  Remove-Item -Recurse -Force ".venv"
}

if (-not (Test-Path ".venv")) {
  $parts = $Python -split '\s+'
  $pyExe = $parts[0]
  $pyArgs = @()
  if ($parts.Length -gt 1) {
    $pyArgs = $parts[1..($parts.Length - 1)]
  }
  Invoke-NativeChecked "create venv" { & $pyExe @pyArgs -m venv .venv }
}

$activate = Join-Path $repo ".venv\Scripts\Activate.ps1"
. $activate
Invoke-NativeChecked "upgrade pip" { python -m pip install --upgrade pip }
Invoke-NativeChecked "install package" { python -m pip install -e . }
Invoke-NativeChecked "unit tests" { python -m unittest discover -s tests }

Write-Host "ANVIL setup complete." -ForegroundColor Green
Write-Host "Run: anvil compile --request 'Build smallest correct plan' --context-file .\examples\sample_context.md --out .\.anvil\plan.json" -ForegroundColor Cyan
