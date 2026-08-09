---
name: voice-clone-elevenlabs-synth-qc
description: 청크 계획을 ElevenLabs로 실제 합성하는 하위 스킬 — request stitching(previous_request_ids·prev/next_text), 잠금된 voice_settings·seed로 일관성을 강제하고, with-timestamps로 문자 정렬을 수집하며 청크 경계 음질을 QC한다. voice-clone-elevenlabs 2단계. "음성 합성 실행 / stitching 합성 / 경계 QC" 맥락에서 발동.
---

# voice-clone-elevenlabs-synth-qc

청크 계획을 받아 실제 오디오를 만든다. **일관성이 전부**다 — 청크마다 목소리가 튀면
사람 손이 안 간 티가 난다. 세 가지로 잠근다: stitching, 고정 설정, 고정 seed.

## 합성 규칙 (검증된 베스트프랙티스)

- **엔드포인트**: `POST /v1/text-to-speech/{voice_id}/with-timestamps`(립싱크·자막용 문자
  정렬을 함께 받는다). auth 헤더 `xi-api-key`. base `https://api.elevenlabs.io`.
- **stitching**: 각 청크 호출에 직전 청크의 `request_id`를 `previous_request_ids`로(최대 3,
  2시간 이내·완료된 것만), 이웃 텍스트를 `previous_text`/`next_text`로 전달. 단
  `enable_logging:false`(zero-retention)면 stitching 비활성 — 끄지 말 것.
- **설정 잠금**: 모든 청크에 **동일** `voice_settings`(stability 중상·style 낮게·
  similarity_boost 기본 0.75) + **동일 `seed`**(재현·일관). 청크 간 설정 드리프트가 불일치
  주원인이다.
- **순서 의존**: stitching은 이전 청크의 request_id가 필요하므로 **체인 순서대로 순차 합성**한다.

## 절차

1. **키·비용 확인** → 검증: `ELEVENLABS_API_KEY` 존재(없으면 deny-by-default 멈춤
   — `[[suite-runtime-keys]]`). 합성은 문자당 종량제 — 총 문자수로 `[[cost-preview-confirm]]`.
2. **순차 합성** → 검증: `chunk-plan.json` 순서대로 각 청크 합성. 응답의 `request_id`를
   기록해 다음 청크의 `previous_request_ids`에 넣는다.
3. **타임스탬프 수집** → 검증: 응답의 `alignment`(문자 start/end times) 저장.
4. **경계 QC** → 검증: 인접 청크 경계에서 (a) 음량 레벨 (b) 말속도 (c) 톤이 급변하지 않는지
   점검(파형/라우드니스 비교). 급변 청크는 stitching 이웃·설정을 재확인하고 재합성.
5. **매니페스트** → 검증: 청크별 request_id·voice_id·model·seed·settings를 기록(재현·추적).

## 출력 계약

`audio/seg-NN.mp3` · `audio/timestamps.json`(문자 정렬) · `audio/synth-manifest.json`.
경계 QC 전부 통과해야 상위 `[[voice-clone-elevenlabs]]`가 완료를 반환. 급변 잔존 시 멈추고 보고.
