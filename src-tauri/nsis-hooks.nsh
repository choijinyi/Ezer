; ezer NSIS 설치 훅 — 업그레이드/재설치 시 잠긴 exe("Error opening file for writing") 문제를
; ★무중단(rename-swap · 2026-07-02)으로 푼다. 종전 taskkill ezerd는 마스터·워커·부서 PTY가
; 전부 ezerd 소유라 "업데이트 = 전 세션 사망"이었다(사용자 불안의 근원).
;
; 원리: Windows는 실행 중 exe의 '덮어쓰기'는 금지하나 '이름 변경(rename)'은 허용(NTFS 동일볼륨).
;   ① GUI(ezer-app.exe)만 종료 — 얇은 클라이언트(main.rs:1 "UI가 죽어도 세션(PTY)은 데몬에
;      살아있다. UI 재시작 = 재attach") → 세션 무손실.
;   ② ezerd.exe·ezer.exe는 죽이지 않고 옆(.prev*.exe)으로 rename → 새 exe를 제자리에 설치.
;      구 데몬은 renamed 파일로 계속 봉사(lame-duck)하고, 새 ezerd 기동이 잔해를 청소한다.
;   ③ rename이 전부 실패할 때만 구 방식(taskkill) 폴백 — 현재보다 나빠질 수 없는 우아한 강등
;      (그 경로는 기존 재시작 복원(maybe_apply_pending_update → ezer restore)이 받친다).
; prev 체인(prev→prev2→prev3): 직전 lame-duck이 아직 살아 prev 파일을 점유 중일 수 있어
; 고정 3칸으로 우회한다(연속 lame-duck 2개 초과는 실사용상 희귀 — 초과 시 폴백 kill).

!macro NSIS_HOOK_PREINSTALL
  ; ① GUI만 종료(세션은 데몬 소유 — 무손실). updater 경로면 이미 종료 중이라 멱등.
  nsExec::Exec 'taskkill /F /T /IM ezer-app.exe'


  ; ② ezerd.exe rename-swap (데몬 무사망)
  IfFileExists "$INSTDIR\ezerd.exe" 0 ezerd_done
  Delete "$INSTDIR\ezerd.prev.exe"          ; 잔해 청소 시도(구 lame-duck 점유 시 실패해도 무시)
  ClearErrors
  Rename "$INSTDIR\ezerd.exe" "$INSTDIR\ezerd.prev.exe"
  IfErrors 0 ezerd_done
  Delete "$INSTDIR\ezerd.prev2.exe"
  ClearErrors
  Rename "$INSTDIR\ezerd.exe" "$INSTDIR\ezerd.prev2.exe"
  IfErrors 0 ezerd_done
  Delete "$INSTDIR\ezerd.prev3.exe"
  ClearErrors
  Rename "$INSTDIR\ezerd.exe" "$INSTDIR\ezerd.prev3.exe"
  IfErrors 0 ezerd_done
  nsExec::Exec 'taskkill /F /T /IM ezerd.exe'   ; ③ 최후 폴백 — 기존 재시작 복원 경로가 받침
ezerd_done:

  ; ② ezer.exe rename-swap (CLI는 단명 프로세스지만 실행 중 잠금 대비 동일 처리)
  IfFileExists "$INSTDIR\ezer.exe" 0 ezer_done
  Delete "$INSTDIR\ezer.prev.exe"
  ClearErrors
  Rename "$INSTDIR\ezer.exe" "$INSTDIR\ezer.prev.exe"
  IfErrors 0 ezer_done
  Delete "$INSTDIR\ezer.prev2.exe"
  ClearErrors
  Rename "$INSTDIR\ezer.exe" "$INSTDIR\ezer.prev2.exe"
  IfErrors 0 ezer_done
  Delete "$INSTDIR\ezer.prev3.exe"
  ClearErrors
  Rename "$INSTDIR\ezer.exe" "$INSTDIR\ezer.prev3.exe"
  IfErrors 0 ezer_done
  nsExec::Exec 'taskkill /F /T /IM ezer.exe'
ezer_done:
  ; ★잠금 스윕 일반화(2026-07-02 실장애: msys-2.0.dll Can't write → Installation Aborted).
  ; 라이브 세션 셸(claude의 bash 훅 등)이 로드한 runtime 이미지(.exe/.dll)는 '덮어쓰기'가 잠기지만
  ; 'rename'은 허용된다(로드된 PE 이미지의 Windows 특성 — ezerd rename-swap과 동일 원리의 전수 일반화).
  ; 설치 트리 전체에서 잠긴 이미지 파일만 <이름>.prev<rand>로 밀어 이름을 비운다 → 추출이 전부 성공.
  ; 잔해(*.prev*)는 새 ezerd 기동이 재귀 청소(P1b 확장). 스크립트는 $PLUGINSDIR에 생성(따옴표 지옥 회피).
  FileOpen $0 "$PLUGINSDIR\unlock-sweep.ps1" w
  FileWrite $0 'param([string]$$Root)$\r$\n'
  FileWrite $0 '$$ErrorActionPreference = "SilentlyContinue"$\r$\n'
  FileWrite $0 'Get-ChildItem -LiteralPath $$Root -Recurse -File | Where-Object { ($$_.Extension -eq ".exe" -or $$_.Extension -eq ".dll") -and ($$_.Name -notlike "*.prev*") } | ForEach-Object {$\r$\n'
  FileWrite $0 '  $$f = $$_.FullName$\r$\n'
  FileWrite $0 '  try { $$s = [IO.File]::Open($$f, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None); $$s.Close() }$\r$\n'
  FileWrite $0 '  catch { try { [IO.File]::Move($$f, $$f + ".prev" + (Get-Random -Maximum 99999)) } catch {} }$\r$\n'
  FileWrite $0 '}$\r$\n'
  FileClose $0
  nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\unlock-sweep.ps1" "$INSTDIR"'

  ; 벨트-앤-브레이스: 스윕이 못 민 잔여 잠금 파일은 스킵하고 설치를 계속한다(Abort 금지).
  ; runtime은 버전 핀 고정(PortableGit·Python·uv·node)이라 스킵=동일 내용이 사실상 전부다.
  SetOverwrite try
  ClearErrors                                 ; 훅 종료 시 에러 플래그 잔류로 설치기 오판 방지
  Sleep 500
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; 바탕화면 바로가기 자동 생성(2026-07-05 박사님 지시). Tauri NSIS 템플릿은 일반 GUI 설치에서
  ; 마침 페이지 체크박스(사용자 클릭)에만 의존해 자동 생성이 아니다 — 템플릿 내장 함수를 직접 호출해
  ; 설치 완료 시 항상 생성한다. 함수 내부 가드를 그대로 재사용: 업데이트(/UPDATE)·무바로가기(/NS)
  ; 모드는 스킵, 기존 .lnk는 타겟만 갱신(멱등 — silent/passive의 템플릿 자체 호출과 중복돼도 무해).
  ; 제거는 템플릿 uninstaller가 "$DESKTOP\<제품명>.lnk"를 지우므로 별도 처리 불요.
  Call CreateOrUpdateDesktopShortcut
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; 제거(uninstall)는 의도적 전면 종료 — 세션 보존 대상이 아니다. lame-duck(.prev*)까지 정리.
  nsExec::Exec 'taskkill /F /T /IM ezer-app.exe'
  nsExec::Exec 'taskkill /F /T /IM ezerd.exe'
  nsExec::Exec 'taskkill /F /T /IM ezer.exe'
  nsExec::Exec 'taskkill /F /T /IM ezerd.prev.exe'
  nsExec::Exec 'taskkill /F /T /IM ezerd.prev2.exe'
  nsExec::Exec 'taskkill /F /T /IM ezerd.prev3.exe'
  nsExec::Exec 'taskkill /F /T /IM ezer.prev.exe'
  nsExec::Exec 'taskkill /F /T /IM ezer.prev2.exe'
  nsExec::Exec 'taskkill /F /T /IM ezer.prev3.exe'
  Sleep 1000
  Delete "$INSTDIR\ezerd.prev.exe"
  Delete "$INSTDIR\ezerd.prev2.exe"
  Delete "$INSTDIR\ezerd.prev3.exe"
  Delete "$INSTDIR\ezer.prev.exe"
  Delete "$INSTDIR\ezer.prev2.exe"
  Delete "$INSTDIR\ezer.prev3.exe"
  ; 잠금 스윕 잔해(*.prev<rand> — 언인스톨러 미추적 파일)까지 정리해 빈 폴더 잔존을 막는다.
  ; 프로세스는 위에서 전부 종료됐으므로 삭제 가능. runtime은 전량 우리 소유 트리다.
  RMDir /r "$INSTDIR\runtime"
  ClearErrors
!macroend
