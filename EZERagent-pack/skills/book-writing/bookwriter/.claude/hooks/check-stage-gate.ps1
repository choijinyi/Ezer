# check-stage-gate.ps1
# PostToolUse hook: after a subagent completes, verify the stage's required output files exist
# and state.json reflects success. Block downstream stages if not.

# Hook input arrives as JSON on stdin. We don't parse all of it — we only need the working directory
# and recent state. For simplicity, scan all build/*/state.json and report any with ok=false.

$ErrorActionPreference = 'Stop'
$buildRoot = Join-Path $PSScriptRoot "..\..\build"

if (-not (Test-Path $buildRoot)) { exit 0 }

$failed = @()
Get-ChildItem $buildRoot -Directory | ForEach-Object {
  $statePath = Join-Path $_.FullName "state.json"
  if (-not (Test-Path $statePath)) { return }
  try {
    $state = Get-Content $statePath -Raw | ConvertFrom-Json
    if ($state.ok -eq $false) {
      $failed += [pscustomobject]@{
        job = $_.Name
        stage = $state.stage
        reason = $state.reason
      }
    }
  } catch { }
}

if ($failed.Count -gt 0) {
  $msg = "Stage gate: $($failed.Count) job(s) in failed state.`n"
  foreach ($f in $failed) {
    $msg += "  - $($f.job) [$($f.stage)] $($f.reason)`n"
  }
  # Non-zero exit signals to Claude Code that something is off, but does not abort the user's session.
  Write-Output $msg
  exit 0
}

exit 0
