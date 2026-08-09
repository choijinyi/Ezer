---
name: suite-runtime-keys
description: 영상 파이프라인 공통 규약 — 외부 서비스 API 키(ElevenLabs·HeyGen 등)를 하드코딩하지 않고 런타임에 받고, 없으면 deny-by-default로 멈춰 정확히 안내하는 패턴. 보급용 배포 전제. "API 키 처리 / BYOK / 런타임 키 / 키 누락 안내" 맥락에서 참조.
---

# suite-runtime-keys

영상 제작 파이프라인은 **보급용**이다 — 오너 한 사람이 아니라 누구나 자기 키만 넣으면
동작해야 한다. 따라서 외부 서비스 자격증명은 코드·스킬에 절대 박지 않고, **사용 시점에
환경변수로 받는다.** 키가 없으면 추측해서 진행하지 않고 멈춘다(deny-by-default).

## 규약 (모든 외부 서비스 호출 스킬이 따른다)

1. **읽기 위치**: 환경변수만 신뢰한다.
   - ElevenLabs → `ELEVENLABS_API_KEY` (헤더 `xi-api-key`)
   - HeyGen → `HEYGEN_API_KEY` (헤더 `x-api-key`)
   - fal.ai → **`FAL_KEY`** (헤더 `Authorization: Key $FAL_KEY` — Bearer 아님. 단 fal MCP는 Bearer)
   - (확장 시: 서비스 공식 env 변수명을 그대로 따른다 — `<SERVICE>_API_KEY` 가정 금지)
2. **부재 시 동작**: 키가 비어 있으면 **그 단계를 실행하지 말고 즉시 멈춘다.** 더미 키·
   추측·우회 금지. 정확한 안내만 출력한다:
   ```
   <SERVICE> API 키 미설정 — `export <SERVICE>_API_KEY=<당신의 키>` 후 재시도.
   발급: <서비스 콘솔 URL>
   ```
3. **하드코딩·로깅 금지**: 키를 파일·커밋·로그·화면에 쓰지 않는다. 디버그 출력에도
   `***`로 가린다. 스킬 예제·문서의 키 자리는 항상 `$<SERVICE>_API_KEY` 플레이스홀더.
4. **검증은 호출로**: "키가 유효한가"는 추론하지 말고 서비스의 가벼운 인증 엔드포인트
   (예: 계정/쿼터 조회)로 1회 확인하고, 실패하면 위 안내로 떨어진다.
5. **전송 경계**: 키가 박힌 요청은 해당 서비스 도메인으로만 나간다. 제3 호스트로
   키가 흘러가는 경로(프록시·텔레메트리)를 만들지 않는다.

## 적용 대상

- `[[voice-clone-elevenlabs]]` (및 하위) — `ELEVENLABS_API_KEY`
- `[[heygen-avatar-render]]` (및 하위) — `HEYGEN_API_KEY`
- `[[media-gen]]` (및 하위) — `FAL_KEY`
- `[[audio-post-music]]` — 생성 음악 사용 시 `ELEVENLABS_API_KEY` 또는 `FAL_KEY`
- `[[video-stitch]]`·`[[video-verify]]`·HyperFrames 렌더 — 키 불필요(로컬 처리).

이 규약은 ezer가 NotebookLM 인증·법제처 OC 키를 다룬 방식(설치·등록은 기계,
키 발급·입력은 사람 단계로 분리)과 동형이다.
