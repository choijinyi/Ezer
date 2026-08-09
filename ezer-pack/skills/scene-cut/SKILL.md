---
name: scene-cut
description: 영상에서 콘텐츠 인지 shot-detect·침묵 트림으로 자동 편집점(컷)을 산출하는 대표 스킬 — provider는 하드코딩하지 않고 ezer_select로 결정론 선택(무키 ffmpeg silencedetect/scene-detect 바닥부터, deny-by-default). 점프컷·클립 경계·몽타주 컷의 공통 편집 토대. "씬컷 / 점프컷 / 컷편집 / 무음제거 / silence trim / shot detection / scene detect / 자동 편집점" 트리거, 또는 clip-factory·cinematic·documentary-montage·screen-demo·talking-head 아키타입의 scene-plan/edit 단계로 발동.
ezer:
  capability: scene-cut
  stability: beta
  cost_class: wall-heavy
  best_for: 콘텐츠 인지 shot-detect·침묵 트림·자동 편집점 — 점프컷·클립 경계·몽타주 컷의 공통 편집 토대
  requires:
    bins: [ffmpeg]
  install:
    - {kind: brew, formula: ffmpeg}
    - {kind: apt, package: ffmpeg}
---

# scene-cut

소스 영상을 **콘텐츠 인지 편집점**(shot-detect·침묵 트림)으로 분해해 자동 컷 계획을 만든다.
이 산출물이 침묵 점프컷(talking-head)·클립 경계(clip-factory)·테마 몽타주(documentary)·
콜아웃 데모(screen-demo)·트레일러(cinematic)의 공통 편집 토대다 — 5개 아키타입이 의존한다.

> ★ezer-native(AGPL 클린룸): OpenMontage의 컷 편집 흐름을 참고했을 뿐 코드·구성을 복사하지
> 않는다. 실제 검출은 아래에서 결정론 선택한 로컬 도구(ffmpeg/PySceneDetect)가 수행한다.

## provider 선택 (하드코딩 금지 — ezer_select 위임)

도구를 손으로 고르지 마라. 카탈로그를 ezer_select로 랭킹해 **설명가능하게** 고른다:

```bash
ezer_select rank --catalog "${EZER_PACK_DIR:-$HOME/.ezer/pack}/round/video_provider_catalog.json" \
  --capability scene-cut --intent "<용도: 점프컷/클립경계/몽타주>" --free-first
```

- **무료·로컬 바닥**: `scenecut_ffmpeg`(ffmpeg `silencedetect`+장면 전환·무키·로컬). 키가 없어도
  항상 가용(deny-by-default 통과) — 그래서 컷 편집은 키 없이도 동작한다.
- 콘텐츠 인지 shot-detect가 필요하면 `scenecut_pyscenedetect`(threshold/adaptive·로컬·무키).
- `--free-first`로 무료 바닥 우선. 특정 도구를 원하면 `--prefer <id>`.

## 산출물 계약 (다운스트림 아키타입이 소비)

`scene_plan.json` (작업 폴더):

```json
{
  "source": "<원본 영상 경로>",
  "provider": "<ezer_select가 고른 id>",
  "method": "silence|content|hybrid",
  "scenes": [
    {"start": 0.0, "end": 3.2, "reason": "silence-gap|shot-change", "keep": true}
  ],
  "duration_s": 0.0
}
```

- **`scenes[]`가 핵심** — 각 컷의 `start`/`end`(소스 경계 안)와 `reason`(왜 컷인지). 다운스트림
  edit 단계가 이걸로 트림·점프컷·클립 추출을 실행한다(D4 매니페스트 `min_items: scenes`로 강제).
- **`keep`**: 침묵·중복 구간 제거 표시. silence-trim은 `keep:false`로 표기(삭제는 edit가 실행).

## 환각0·producer≠evaluator (불가침)

- **편집점은 소스 경계 안**: 모든 `end ≤ duration_s`, `start ≤ end`, 인접 컷 비중첩. 벗어나면
  컷 계획 무효 — 다듬지 말고 재검출(garbage-in 차단).
- **빈 컷 금지**: `scenes`를 자리채움(빈 객체·0길이)으로 채우지 마라 — D4 `min_items`가 비어있지
  않은 항목만 세므로 무의미 항목은 게이트를 통과하지 못한다(필요조건 floor일 뿐).
- 검증은 산출 노드가 자가채점하지 않는다 — `video-verify`(별 노드)가 컷 자연스러움·커버리지를
  독립 확인한다(D1 verdict 계약·점수금지).

## 거버넌스 배선

- 위임 티켓 전제: `--requires-skills scene-cut`(D6 자동주입). 흔히 `transcription`과 함께(말 경계).
- 아키타입 매니페스트(D4) scene-plan 단계 success_criteria 예:
  `{"kind":"json_valid"}` + `{"kind":"field_present","value":"scenes"}` +
  `{"kind":"min_items","value":{"field":"scenes","min":2}}`(점프컷 커버리지 강제).
- cost_class=wall-heavy: 긴 영상은 검출 후 임시 프레임·로그 정리(자원 거버넌스).
