# dist-win/ — 로컬 빌드 스크래치 (소비자 배포본 아님)

> **RC-14 (T2)**: 이 디렉토리는 **로컬 개발 빌드 잔재**다. Windows **소비자 배포본이 아니다.**

## 소비자 Windows 배포본 = GitHub 릴리스 (NSIS)
- 채널: `choijinyi/Ezer` 릴리스의 `EZERagent_<ver>_x64-setup.exe` (NSIS 자기완결 설치본)
- 동봉: PortableGit(bash) + Python embeddable runtime (`<install>\runtime\`) — release.yml/windows-build.yml이 빌드
- v0.5.0 setup.exe 실측: runtime 8,339 파일 동봉 확인 (T1.1 R2에서 RC-8 "미도달" 오판 기각)

## 이 폴더의 내용물 (혼동 금지)
- `*.wxs` — **레거시 WiX 소스**(구 MSI 빌드). 프로젝트는 NSIS로 이전됨 — 참고용 잔재.
- `*.msi` / `*.zip` / `zip/` — 로컬 빌드 산출물. **`.gitignore`로 추적 제외**(배포 채널과 무관).

## 주의 (T1 R2 교훈)
`dist-win/`의 파일 버전(구 v0.2.2 WiX 등)을 **소비자 배포본으로 오독하지 말 것.** 소비자에게 도달하는
Windows 배포본은 위 GitHub 릴리스(NSIS setup.exe)이며 runtime을 동봉한다. 로컬 잔재로 "runtime
미도달"을 단정한 것이 T1 RC-8 오판이었다(master 실물 실측으로 기각).
