---
name: video-stitch-compositing
description: 아바타를 모든 구간에 노출시키는 컴포지팅 하위 스킬 — 좌측 카드 슬라이드인 / 드롭섀도 둥근 크롭 모드, 전환·이징·페이싱을 사람 편집자 수준으로 적용한다. video-stitch 컴포지팅 관문. "아바타 컴포지팅 / 카드 슬라이드인 / 둥근 크롭 / 전환 페이싱" 맥락에서 발동.
---

# video-stitch-compositing

"아바타 항상 노출"(원본 사양)을 보장하고, 컷·전환·여백을 프로페셔널하게 만든다.

## 컴포지팅 모드 (구간별 택1)

- **(a) 좌측 카드 슬라이드인** — 아바타를 좌측 카드로, 우측에 그래픽/B-roll. 카드 진입은
  슬라이드+이징. 설명형 구간에 적합.
- **(b) 드롭섀도 둥근 크롭** — 아바타를 둥근 모서리+드롭섀도로 코너 오버레이(PIP). 풀스크린
  그래픽/B-roll 위에 아바타를 작게. 둥근 반경·그림자 오프셋·블러를 전 구간 일관.

## 절차

1. **모드 배치** → 검증: 각 구간에 (a)/(b)를 배정. 모든 프레임에 아바타가 보이는지(가림·
   사라짐 0). 구간 전환에서 아바타가 끊기지 않게.
2. **전환·페이싱** → 검증: 컷/디졸브/슬라이드 전환에 일관 이징. 너무 잦거나 느린 전환 배제.
   여백·세이프영역 준수(화면 밖 이탈 0).
3. **일관성** → 검증: 카드 위치·둥근 반경·드롭섀도 파라미터가 영상 전체에서 동일.

## op→filtergraph 매핑 (결정론 실행 테이블 — W2-4)

LLM은 `edit_decisions.json`(W0-2 정전 IR)에 **타입드 데이터**(`mode`·`transition` 닫힌 enum)만
내고, 컴포지팅 실행기는 아래 **고정 매핑 테이블**을 소비한다 — 산문으로 필터 문자열을 즉흥
작성하지 마라(환각 표면). OpenCut의 "TS는 어떤 shader인지 데이터로 결정, Rust가 실행" 분리와
동형(`effects-renderer.md:16`): *정책=데이터(IR), 기제=결정론 실행기*. 테이블에 없는 op는
**fail-loud**(edit_decisions 스키마가 enum으로 1차 차단·실행기가 2차 거부).

| IR `mode` | FFmpeg 필터그래프 골격(파라미터는 IR·일관성 상수에서) |
|---|---|
| `fullscreen` | 그래픽/B-roll 풀스크린 + 아바타 PIP 오버레이(아바타 미노출 0 규칙) |
| `left-card` | 아바타 좌측 카드 `scale`+`pad` → `overlay=x='슬라이드 이징(t)':y=Y`, 우측 콘텐츠 |
| `rounded-crop-pip` | 아바타 둥근 크롭(`geq`/alpha 마스크)+드롭섀도(`boxblur`+offset) → 코너 `overlay` |

| IR `transition` | FFmpeg |
|---|---|
| `cut` | 하드 concat(필터 없음·경계 keyframe 강제 → W2-3 replay-verify) |
| `dissolve` | `xfade=transition=fade:duration=D:offset=O` |
| `slide` | `xfade=transition=slideleft:duration=D:offset=O` |

- 둥근 반경·그림자 오프셋·블러·카드 위치는 **전 구간 일관 상수**(절차 3) — IR이 아닌 프로젝트
  상수로 두고, 수치는 `ezer_params`(W1-2)로 coerce해 범위-밖 차단.

## 출력 계약

컴포지팅된 트랙 + `final/timeline.json`에 구간별 모드·전환 기록(검증 `[[video-verify-visual]]`의
대조 기준). 상위 `[[video-stitch]]`로 반환. 아바타 미노출 프레임이 하나라도 있으면 보고·수정.
