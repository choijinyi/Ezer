# verify-decisions.ps1
# UserPromptSubmit hook: if any active job has unanswered decisions, surface them so the user
# can't accidentally proceed to the next stage without seeing them.

$ErrorActionPreference = 'Stop'
$buildRoot = Join-Path $PSScriptRoot "..\..\build"

if (-not (Test-Path $buildRoot)) { exit 0 }

$pending = @()
Get-ChildItem $buildRoot -Directory | ForEach-Object {
  $decisionsPath = Join-Path $_.FullName "decisions.md"
  $polishPath = Join-Path $_.FullName "polish-proposals.md"
  $structQ = 0
  $polishQ = 0
  if (Test-Path $decisionsPath) {
    $c = Get-Content $decisionsPath -Raw
    if ($c -match 'Decided:\s*<TODO>') {
      $structQ = ([regex]::Matches($c, 'Decided:\s*<TODO>')).Count
    }
  }
  if (Test-Path $polishPath) {
    $c = Get-Content $polishPath -Raw
    if ($c -match 'Apply:\s*<TODO>') {
      $polishQ = ([regex]::Matches($c, 'Apply:\s*<TODO>')).Count
    }
  }
  if ($structQ -gt 0 -or $polishQ -gt 0) {
    $msg = "  - $($_.Name):"
    if ($structQ -gt 0) { $msg += " $structQ structural" }
    if ($polishQ -gt 0) { $msg += " $polishQ polish" }
    $pending += $msg
  }
}

if ($pending.Count -gt 0) {
  Write-Output "Pending decisions (mark answers in decisions.md / polish-proposals.md):"
  $pending | ForEach-Object { Write-Output $_ }
}

exit 0
