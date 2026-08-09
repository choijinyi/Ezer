---
name: script-writer-voice-prep
description: 검증된 대본을 음성 합성용 청크로 분절하는 하위 스킬 — 자연스러운 문장·절 경계에서 쪼개고 연속성 메타(prev/next 텍스트)와 시각 큐를 보존한다. script-writer 6단계, voice-clone-elevenlabs의 입력 생성. "대본 청크 분절 / 음성 준비 / 나레이션 분할" 맥락에서 발동.
---

# script-writer-voice-prep

긴 대본을 통째로 합성하면 청크 간 프로소디가 튄다. 그래서 짧게 나눠 합성하되 — **중요:
"60초"는 구식 기준이다.** 검증된 현재 베스트프랙티스(ElevenLabs request stitching, 2024+)는:
청크 길이를 시간이 아니라 **모델 글자수 한도** 기준으로 잡고, 항상 **문장 경계**에서 끊고,
청크 간 연속성은 **stitching 메타(이전/다음 텍스트·request id)** 로 잇는다. 짧게 자르는 게
아니라 *이어붙이는 정보를 보존*하는 게 핵심이다.

이 스킬은 **대본 측 분절**을 한다(문장 경계 + 연속성 메타 + 시각 큐). 모델 글자수 한도
검증과 stitching 순서 확정은 `[[voice-clone-elevenlabs-chunk]]`가 받아 마무리한다.

## 절차

1. **문장 분할** → 검증: 대본을 문장 단위로 분해(약어·소수점 오분할 주의).
2. **세그먼트 합치기** → 검증: 문장을 모아 자연 세그먼트(보통 한 문단 또는 한 시각 큐 구간)를
   만든다. **항상 문장 끝에서 닫는다**(문장 중간 분할 금지). 시간은 타임라인 계획용 추정만.
3. **연속성 메타** → 검증: 각 세그먼트에 직전 끝 문장·다음 첫 문장을 `prev_text`/`next_text`로
   기록 — 합성 stitching의 입력(`[[voice-clone-elevenlabs-synth-qc]]`).
4. **시각 큐 보존** → 검증: `outline.md`의 시각 큐를 해당 세그먼트에 매핑해 보존.

추정 시간 기준(타임라인용): 영어 ~150 wpm, 한국어 ~330 음절/분.

## 출력 계약

`script.chunks.json` — `[{id, text, est_seconds, prev_text, next_text, visual_cue}]`.
문장 경계 분할, 연속성 메타·시각 큐 보존(글자수 한도 검증은 다음 단계). 상위
`[[script-writer]]`로 반환 → `[[voice-clone-elevenlabs]]`의 입력.
