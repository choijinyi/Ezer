# aiterm Windows E2E — 게스트(Windows 11)에서 실행
# 소스: \\Mac\Home 공유 폴더 → C:\aiterm-src 복사 후 네이티브 빌드·named pipe 검증
$ErrorActionPreference = "Continue"

Write-Output "=== [1/6] source sync ==="
robocopy "\\Mac\Home\Desktop\Ezer\aiterm" "C:\aiterm-src" /MIR /XD target node_modules dist .git gen android ios src-tauri ui /NFL /NDL /NJH /NJS | Out-Null
Set-Location C:\aiterm-src
Get-ChildItem | Select-Object -ExpandProperty Name

Write-Output "=== [2/6] cargo build (core only) ==="
cargo build -p aiterm 2>&1 | Select-Object -Last 4
if ($LASTEXITCODE -ne 0) { Write-Output "BUILD FAILED"; exit 1 }

Write-Output "=== [3/6] unit tests ==="
cargo test --lib 2>&1 | Select-String "test result"

Write-Output "=== [4/6] daemon start (named pipe) ==="
Stop-Process -Name aitermd -Force -ErrorAction SilentlyContinue
Start-Process -FilePath ".\target\debug\aitermd.exe" -WindowStyle Hidden
Start-Sleep 2
.\target\debug\aiterm.exe ping
.\target\debug\aiterm.exe identify

Write-Output "=== [5/6] surface E2E: create -> send -> read ==="
$ref = .\target\debug\aiterm.exe new-surface --title "win-test"
Write-Output "created: $ref"
Start-Sleep 2
.\target\debug\aiterm.exe send --surface $ref "echo HELLO_FROM_WINDOWS_PIPE"
.\target\debug\aiterm.exe send-key --surface $ref Return
Start-Sleep 2
Write-Output "--- screen ---"
.\target\debug\aiterm.exe read-screen --surface $ref

Write-Output "=== [6/6] feed E2E ==="
.\target\debug\aiterm.exe feed push --title "win approval" --body "windows e2e"
.\target\debug\aiterm.exe feed list
.\target\debug\aiterm.exe close-surface $ref
Stop-Process -Name aitermd -Force -ErrorAction SilentlyContinue
Write-Output "=== DONE ==="
