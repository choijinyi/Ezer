# RELIABILITY.md

bookwriter는 비동기 빌드 파이프라인이다. 신뢰성 = "사용자의 글을 잃지 않는다" + "약속한 시간 안에 끝낸다".

## 불변 규칙

1. **원본은 절대 덮어쓰지 않는다** — `build/<job>/source.md`는 ingestor가 1회만 쓰고 read-only.
2. **각 단계는 멱등이다** — 같은 입력 → 같은 출력. 재실행이 안전해야 한다.
3. **부분 실패는 다음을 차단한다** — editor가 깨지면 typesetter는 시작하지 않는다.
4. **사용자 데이터는 7일 후 삭제** — `dist/<job>` 보존, `build/<job>` 자동 정리.

## 장애 모드

| 장애 | 감지 | 복구 |
|---|---|---|
| ingestor가 PDF 파싱 실패 | exit code ≠ 0 | 사용자에게 OCR 안내 |
| AI Gateway 타임아웃 | 30s no response | 1회 재시도, 다른 모델로 폴백 |
| Typst 컴파일 에러 | stderr 캡처 | `errors.log` 노출, 빌드 중단 |
| Blob 업로드 실패 | HTTP ≠ 2xx | 지수 백오프 3회, 그 후 사용자 알림 |
| 작업 30분 초과 | timeout 훅 | 작업 종료, 부분 산출물 보존 |

## 재실행 전략 (H1 결정 반영)

**1 job = 1 원고 스냅샷.** 원고 내용이 바뀌면 새 job-id를 발급받는다. 같은 job 안에서는 콘텐츠 해시 비교를 하지 않는다.

- **Resume**: 같은 job-id에서 `/run` 재호출 → 마지막 성공 단계 다음부터 이어달리기.
- **Single-stage rerun**: `/run <job> edit` 같이 단계 지정 → 그 단계만 강제로 다시.
- **New build**: 원고 수정 후 `/new manuscripts/mybook` → 새 job-id로 처음부터.
- **Template branch**: 다른 템플릿으로 시도하려면 `book.json.template`을 바꾸고 새 job 발급 (job 디렉토리는 격리되므로 비교 가능).

## 관측

- 단계별 시간/메모리 로그 → Vercel Functions 기본 로그
- 사용자별 빌드 성공률 → 7일 슬라이딩 윈도우 ≥ 95% 목표
- p95 빌드 시간 < 5분 (50p), < 15분 (200p)

## 백업

- 산출물(`dist/`)은 Vercel Blob (자동 복제).
- 사용자가 명시적으로 "보관" 누른 작업은 30일 보존.
- 시스템 자체 코드는 Git, 템플릿도 Git. 데이터 백업은 사용자 책임 (다운로드 안내).

## 사고 대응

`docs/exec-plans/active/incident-<date>.md`로 시작:
1. 무엇이 깨졌나 (사용자 영향)
2. 무엇이 원인이었나 (확정 후)
3. 어떻게 막았나 (당장)
4. 어떻게 재발 방지하나 (영구)

## 의도적 비목표

- 99.9% SLA 약속 안 한다 (게스트 무료 빌드는 best-effort).
- 다중 리전 액티브-액티브 안 한다 (Vercel 기본만).
- 자동 롤백 안 한다 — 빌드는 멱등이라 사용자가 재실행하면 된다.
