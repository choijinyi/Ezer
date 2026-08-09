---
name: voice-clone-elevenlabs
description: 검증된 대본 청크를 ElevenLabs로 일관된 나레이션 오디오로 합성하는 대표 스킬 — 음성 클론(voice_id) 확보, 글자수 한도 청킹, request stitching 연속성, 잠금된 settings·seed, 문자 타임스탬프까지. "음성 합성 / 보이스 클론 / 나레이션 / elevenlabs tts" 트리거, 또는 youtube-video-pipeline 2단계로 발동.
---

# voice-clone-elevenlabs

대본을 멀티분 나레이션으로 합성한다. 핵심 난제는 **여러 청크를 이어붙여도 같은 목소리처럼
들리게** 하는 것 — ElevenLabs의 검증된 방식(request stitching + 설정 잠금)으로 해결한다.

> ★실측 정정(2026): 원본 워크플로우의 "60초 청크로 잘라 음성 열화 방지"는 **구식**이다.
> API는 시간이 아니라 **글자수**로 제한하고, 청크 간 프로소디 점프의 진짜 해법은 짧게
> 자르는 게 아니라 **request stitching**(이전 청크의 request id·텍스트를 다음 호출에 전달)이다.
> (출처: ElevenLabs request-stitching cookbook)

## 키·도구

- 키: `ELEVENLABS_API_KEY` (런타임 — `[[suite-runtime-keys]]`, 없으면 deny-by-default 멈춤).
- 공식 자산 채택: ElevenLabs는 공식 스킬(`npx skills add elevenlabs/skills`의 `text-to-speech`·
  `setup-api-key`)과 MCP(`elevenlabs/elevenlabs-mcp`)를 제공한다 — **raw API 호출 기계는 공식
  스킬/MCP에 위임**하고, 이 스킬은 그 위에 *파이프라인 정책*(올바른 청킹·stitching·설정 잠금·
  타임스탬프)을 강제한다. preflight C26이 공식 스킬 설치를 검증한다.

## 하위 스킬 오케스트레이션

1. `[[voice-clone-elevenlabs-chunk]]` — `script.chunks.json`을 모델 글자수 한도에 맞춰
   확정하고 stitching 순서(체인)를 만든다.
2. `[[voice-clone-elevenlabs-synth-qc]]` — 청크별 합성(stitching·설정 잠금) + 경계 음질 QC +
   문자 타임스탬프 수집.

## 절차

1. **voice_id 확보** → 검증: 사용할 음성 결정. 클론이면 `POST /v1/voices/add`(Instant Voice
   Cloning, ~2분 미만 샘플) 또는 기존 `voice_id` 사용. PVC는 Creator+ 플랜·captcha 필요.
   라이브러리 음성이면 그 `voice_id`.
2. **모델 선택** → 검증: 나레이션 기본은 `eleven_multilingual_v2`(안정·고품질·stitching 호환,
   글자한도 10,000). 표현형 오디오태그가 꼭 필요하면 `eleven_v3`(단 alpha·**stitching 불가**)
   — 트레이드오프를 명시하고 결정.
3. **청킹** → 검증: `[[voice-clone-elevenlabs-chunk]]` — 문장 경계, 모델 글자한도 미만, stitch 체인.
4. **합성+QC** → 검증: `[[voice-clone-elevenlabs-synth-qc]]` — 잠금 설정·seed, stitching,
   `/with-timestamps`로 문자 정렬 수집, 경계 음질 QC.

## 출력 계약

- `audio/seg-NN.mp3` — 세그먼트별 오디오(동일 voice_id·settings·seed)
- `audio/timestamps.json` — 문자 단위 alignment(이후 립싱크·자막 정렬용)
- `audio/synth-manifest.json` — `[{id, request_id, voice_id, model_id, seed, settings}]`(재현·stitching 추적)
- 경계 음질 QC 결과. 상위 `[[youtube-video-pipeline]]`로 반환 → `[[heygen-avatar-render]]` 입력.
