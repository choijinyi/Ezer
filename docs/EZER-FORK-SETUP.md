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

## 3. 홈페이지·연락처 참조 (의도적 보존)

다음은 **업스트림 값 그대로 남겨 두었다** — 바꿀 값이 정해지지 않았기 때문이다.

| 위치 | 값 | 조치 필요 |
|---|---|---|
| `LICENSE` | `cysinsight@gmail.com` | **변경 금지** — MIT 원저작권 고지 |
| `SECURITY.md` | `cysinsight@gmail.com` | 취약점 신고처를 Ezer 담당자 주소로 교체 |
| `src-tauri/src/main.rs` 허용목록 | `cysinsight.com` | Ezer 홈페이지가 생기면 교체 |
| `ui/src/main.ts`·`updateplan.ts` | `www.cysinsight.com` 안내 문구 | 본체 수동 다운로드 안내 — GitHub Releases 주소로 교체 권장 |

## 4. 아이콘·브랜드 아트워크

`src-tauri/icons/*`는 업스트림 아이콘 그대로다(바이너리라 리네임 대상이 아니었다).
Ezer 로고로 교체하려면 같은 파일명·크기로 덮어쓴다.

## 5. pro 라이선스 발급키

`src/license.rs`는 verify-only다(발급키 미탑재 — 설계상 정상). 무료 기능은 전부 동작하며,
pro 티어 라이선스를 발급하려면 별도 서명키가 필요하다. 발급 계획이 없으면 그대로 두면 된다.

## 6. 레거시 식별자 (브랜드 아님 — 그대로 둠)

`AITERM_SOCKET` 환경변수와 `ui/package.json`의 패키지명 `aiterm-ui`는 cys 브랜드가 아니라
업스트림의 더 오래된 내부 이름이다. 동작에 영향이 없어 리네임하지 않았다.
