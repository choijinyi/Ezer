---
name: voice-clone-elevenlabs-chunk
description: 대본 세그먼트를 ElevenLabs 모델 글자수 한도에 맞춰 확정하고 request stitching 체인(순서·이웃 관계)을 구성하는 하위 스킬. 시간이 아니라 글자수로 자르고 문장 경계를 지킨다. voice-clone-elevenlabs 1단계. "음성 청킹 / stitching 체인 / 글자수 분할" 맥락에서 발동.
---

# voice-clone-elevenlabs-chunk

`script.chunks.json`(대본 측 세그먼트)을 받아 합성 단위로 확정한다. **자르는 축은 시간이
아니라 글자수**다(API 제한이 글자 기준). 그리고 청크 간 연속성을 위해 stitching 체인을 짠다.

## 절차

1. **모델 한도 확인** → 검증: 선택 모델의 글자한도(예: `eleven_multilingual_v2`=10,000,
   `eleven_v3`=5,000)를 기준값으로 잡는다. 안전 마진으로 한도의 ~80%를 상한 목표로.
2. **세그먼트 재패킹** → 검증: 대본 세그먼트를 합쳐도/나눠도 **항상 문장 경계**에서 끊고,
   각 청크가 글자 상한 미만이 되게 한다. 한 청크가 한도를 넘으면 문장 단위로만 분할.
3. **stitch 체인 구성** → 검증: 청크를 순서 배열로 만들고 각 청크에 `prev_id`/`next_id`를
   부여(최대 3 이웃까지 stitching id로 쓸 수 있음). `prev_text`/`next_text`는 대본 측 메타에서 보존.
4. **stitching 적용성 표시** → 검증: 모델이 `eleven_v3`이면 stitching 불가 → 체인 메타에
   `stitch:false`로 표시하고 설정 잠금·seed에 더 의존하라고 경고.

## 출력 계약

`audio/chunk-plan.json` — `[{id, text, char_count, prev_id, next_id, prev_text, next_text,
visual_cue, stitchable}]`. 각 청크 글자한도 미만·문장 경계·stitch 체인 정의. 상위
`[[voice-clone-elevenlabs]]`로 반환 → `[[voice-clone-elevenlabs-synth-qc]]`의 입력.
