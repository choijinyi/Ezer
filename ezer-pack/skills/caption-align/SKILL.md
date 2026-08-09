---
name: caption-align
description: 전사 텍스트를 음성에 단어 단위로 정렬해 자막 타이밍(큐)을 생성하는 대표 스킬 — provider는 하드코딩하지 않고 ezer_select로 결정론 선택(무키 whisperx forced-alignment 바닥부터, deny-by-default). 현 video-stitch-captions의 audio-sync가 *검사*만 한다면 이 스킬은 타이밍을 *생성*한다. "자막 정렬 / 캡션 타이밍 / forced alignment / 단어 싱크 / 자막 큐 / subtitle timing / SRT 타임코드" 트리거, 또는 localization-dub·podcast-repurpose 아키타입의 assets 단계로 발동.
ezer:
  capability: caption-align
  stability: beta
  cost_class: wall-heavy
  best_for: 전사 텍스트↔음성 단어 단위 forced-alignment로 자막 큐 타이밍 생성 — 자막·더빙 싱크의 토대
  params:
    - {key: max_words, type: number, default: 7, min: 1, max: 14, step: 1}
    - {key: max_chars, type: number, default: 42, min: 10, max: 80, step: 1}
    - {key: gap_split_s, type: number, default: 0.8, min: 0, max: 5, step: 0.1}
    - {key: min_duration_s, type: number, default: 1.0, min: 0, max: 10, step: 0.1}
---

# caption-align

전사 텍스트(또는 번역문)를 음성에 **단어 단위로 강제 정렬**(forced alignment)해 자막 큐의
정확한 타임코드를 생성한다. `transcription`이 단어 타임스탬프를 주면, 이 스킬은 줄바꿈·읽기속도·
화면 길이를 고려한 **자막 큐**로 묶는다. localization-dub·podcast-repurpose 2 아키타입이 의존한다.

> ★ezer-native(AGPL 클린룸): forced-alignment 흐름을 참고했을 뿐 코드를 복사하지 않는다.
> 실제 정렬은 아래에서 결정론 선택한 로컬 도구(WhisperX-align/aeneas)가 수행한다.

## provider 선택 (하드코딩 금지 — ezer_select 위임)

```bash
ezer_select rank --catalog "${EZER_PACK_DIR:-$HOME/.ezer/pack}/round/video_provider_catalog.json" \
  --capability caption-align --intent "<용도: 자막/더빙싱크>" --free-first
```

- **무료·로컬 바닥**: `align_whisperx`(WhisperX forced-alignment·무키·로컬·`transcription`의 whisperx
  모델 재사용). 키가 없어도 항상 가용 — 자막 정렬은 키 없이 동작한다.
- 문장 단위·다국어 정렬엔 `align_aeneas`(로컬·무키). `--free-first`로 무료 바닥 우선.

## 입력·산출물 계약

- **입력**: `transcript.json`의 `segments[].words[]`(start/end) — `transcription` 산출물. 단어
  타임스탬프가 없으면 정렬 불가 → 먼저 `transcription`을 단어 단위로 재실행(garbage-in 차단).
  URL 소스는 `transcription/bin/transcribe_channel.py`를 `--want-words`로 호출하면 자막(단어
  타임스탬프 없음)을 자동 건너뛰고 `transcriber_whisperx` ASR로 격상해 단어 단위를 보장한다(OPP-09).
- **산출**: `captions.json`(작업 폴더):

```json
{
  "source": "<원본 미디어 경로>",
  "provider": "<ezer_select가 고른 id>",
  "language": "<자막 언어>",
  "cues": [
    {"start": 0.0, "end": 2.4, "text": "...", "words": [{"w": "...", "start": 0.0, "end": 0.4}]}
  ]
}
```

- **`cues[]`가 핵심** — 각 큐의 `start`/`end`(소스 경계 안)·읽기 가능한 길이(과밀 금지). 다운스트림
  caption 렌더가 이걸 소비(D4 매니페스트 `field_present: cues`로 강제 가능).

## 결정론 큐 셰이핑 (제로토큰 — caption_shape.py)

forced-alignment가 단어별 start/end를 주면, 단어→큐 그룹핑은 **LLM이 아니라 결정론 도구**가 한다
(제로토큰·같은 입력→같은 출력). 산문으로 "적당히 묶어라"는 환각 표면이므로 금지 — 팩 동봉
`bin/caption_shape.py`로 규칙 셰이핑한다(OpenCut 결정론 자막 셰이핑 발상):

```bash
python3 caption_shape.py shape --input transcript.json --out captions.json \
  --max-words 7 --max-chars 42 --gap-split 0.8 --min-duration 1.0
```

- 규칙: **N-words/큐**(가독성) + **max-chars**(한 줄 과밀 방지) + **gap-split**(자연 휴지서 분할) +
  **min-duration**(짧은 큐 표시시간 보장) + **비중첩**(다음 큐 start 침범 금지). 출력 `cues[]`는
  위 산출 계약과 동일 형식.
- 파라미터는 frontmatter `ezer.params`(ParamDefinition)로 선언 — 호출 전 `ezer_params coerce`로
  범위-밖 값을 거부한다(가치 게이트). 손튜닝 수치를 산문에 박지 마라.

## 환각0·producer≠evaluator (불가침)

- **타이밍은 소스 경계 안**: 모든 `end ≤ duration`, `start ≤ end`, 큐 비중첩. 벗어나면 무효.
- **텍스트 변조 금지**: 정렬은 타이밍만 부여한다 — 전사/번역 텍스트를 지어내거나 바꾸지 마라.
- 검증은 자가채점하지 않는다 — `video-verify-audio-sync`(별 노드)가 자막↔오디오 정합을 독립
  확인한다(D1 verdict 계약·점수금지).

## 거버넌스 배선

- 위임 티켓 전제: `--requires-skills transcription,caption-align`(D6 자동주입 — 단어 타임스탬프 선행).
- 아키타입 매니페스트(D4) assets 단계 success_criteria 예:
  `{"kind":"json_valid"}` + `{"kind":"field_present","value":"cues"}` +
  `{"kind":"min_items","value":{"field":"cues","min":1}}`.
- cost_class=wall-heavy: 긴 미디어는 정렬 후 임시파일 정리(자원 거버넌스).
