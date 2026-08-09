# Ezer 포크 — 배포 전 마무리 항목

Ezer agent는 cys-terminal(MIT)의 리브랜딩 파생본이다. 식별자·경로·저장소 배선은 전부
교체됐지만, **서명키처럼 원저작자만 보유한 비밀은 승계되지 않는다.** 릴리스를 실제로
배포하기 전에 아래를 처리해야 한다. 소스 업로드와 CI 빌드 자체는 이것들 없이도 동작한다.

## 1. Tauri 업데이터 서명키 (릴리스 배포 시 필수)

`src-tauri/tauri.conf.json`의 `plugins.updater.pubkey`는 **업스트림 키페어의 공개키**다.
Ezer가 자기 릴리스에 서명하려면 자체 키페어가 필요하다.

```bash
# 키페어 생성 (Tauri CLI)
bunx @tauri-apps/cli signer generate -w ~/.ezer-updater.key
```

- 출력된 **공개키**를 `src-tauri/tauri.conf.json`의 `pubkey`에 붙여 넣는다.
- **개인키**와 암호를 GitHub 저장소 Secrets에 등록한다:
  - `TAURI_SIGNING_PRIVATE_KEY`
  - `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
- 개인키는 저장소에 커밋하지 않는다.

이 작업 전까지 `release.yml`·`pack-release.yml`의 서명 단계는 실패한다.

## 2. 팩 서명 신뢰키

`ezer-pack/trusted-keys.json`의 `key_id`(`39E60A702949D6C3`)는 업스트림 키다.
`pubkey` 필드는 공개 저장소에서 비어 있고 릴리스 시 주입되는 구조다. 자체 팩 채널을
운영하려면 minisign 키페어를 만들어 `key_id`·`pubkey`를 교체하고 `not_after`를 정한다.

## 3. 저작자·연락처·홈페이지 (반영 완료)

오너 지정값으로 교체했다 — 저작자 **Choi jinyi**, 연락처 이메일 `ezer.agent` (gmail),
홈페이지 **www.kaea.ai.kr**.

| 위치 | 반영 내용 |
|---|---|
| `LICENSE` | Choi jinyi 저작권을 첫 줄에, 업스트림 CYSJavis 고지를 그 아래 유지(MIT 의무) |
| `README.md` · `README.en.md` · `SECURITY.md` | 연락처·취약점 신고처를 Ezer 주소로 교체 |
| `src-tauri/src/main.rs` 호스트 허용목록 | `kaea.ai.kr` (정확일치 + 서브도메인이라 `www.` 포함) |
| `ui/src/main.ts`·`updateplan.ts`·`updateplan.test.ts` | 본체 수동 다운로드 안내를 `www.kaea.ai.kr`로 |
| `docs/RELEASE.md` | 배지 안내 문구의 홈페이지 주소 교체 |

남아 있는 `cysinsight` 문자열은 두 종류뿐이며 **연락처가 아니다**: ①`ezer-pack/bin/ezer_org.py`
등의 **테스트 픽스처 계정 핸들** ②`scripts/secret-scan.sh`의 **개인 프로필 탐지 패턴**.
둘 다 브랜드 표기가 아니라 동작 요소라 건드리지 않았다.

> 이 문서에 이메일 주소를 문자 그대로 적지 마라 — `scripts/secret-scan.sh`가 PUBLIC 발행 전
> 하드 게이트로 차단한다(허용은 `README.md`·`README.en.md`·`SECURITY.md`뿐).

## 4. 아이콘·브랜드 아트워크

`src-tauri/icons/*`는 업스트림 아이콘 그대로다(바이너리라 리네임 대상이 아니었다).
Ezer 로고로 교체하려면 같은 파일명·크기로 덮어쓴다.

## 5. pro 라이선스 발급키

`src/license.rs`는 verify-only다(발급키 미탑재 — 설계상 정상). 무료 기능은 전부 동작하며,
pro 티어 라이선스를 발급하려면 별도 서명키가 필요하다. 발급 계획이 없으면 그대로 두면 된다.

## 6. 레거시 식별자 (브랜드 아님 — 그대로 둠)

`AITERM_SOCKET` 환경변수와 `ui/package.json`의 패키지명 `aiterm-ui`는 cys 브랜드가 아니라
업스트림의 더 오래된 내부 이름이다. 동작에 영향이 없어 리네임하지 않았다.
