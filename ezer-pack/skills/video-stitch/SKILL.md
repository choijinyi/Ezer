---
name: video-stitch
description: 아바타 클립·HyperFrames 모션그래픽·생성형 B-roll·자막·배경음악을 하나의 완성 영상으로 합성하는 대표 편집 스킬 — 컴포지팅(아바타 항상 노출)·B-roll 배치·자막 번인을 하위 스킬로 오케스트레이션하고 FFmpeg로 마스터 렌더한다. "영상 합성 / 편집 / 클립 결합 / 컴포지팅 / 자막" 트리거, 또는 youtube-video-pipeline 합성 단계로 발동.
---

# video-stitch

여러 트랙(아바타·모션그래픽·B-roll·자막·음악)을 사람 편집자처럼 하나로 합친다. 모션그래픽
*제작*은 **HyperFrames 공식 `/hyperframes` 스킬**(HTML), B-roll *생성*은 `[[media-gen]]`,
음악은 `[[audio-post]]`가 한다 — 이 스킬은 그 결과들을 **편집·합성**한다.

> 편집은 결정론적 타임라인 작업이지만, B-roll·자막·"아바타 항상 노출" 컴포지팅이 더해지며
> 별개 편집 관심사로 갈라져 대표+하위 구조로 운영한다.

## 하위 스킬 오케스트레이션

1. `[[video-stitch-compositing]]` — 아바타 항상 노출(좌측 카드/둥근 크롭) + 전환·페이싱.
2. `[[video-stitch-broll]]` — `[[media-gen]]`의 생성형 B-roll을 타임라인 적소에 배치.
3. `[[video-stitch-captions]]` — `audio/timestamps.json` 기반 동기 자막 번인.

## 절차

0. **편집-결정 IR 저작·검증(정전 입력)** → 검증: 렌더 전에 `edit_decisions.json`을 정전 IR로
   저작한다 — `schema_version:1` · `render_runtime` 명시 고정(무음 swap=위반·SF-RENDER-RUNTIME-SWAP)
   · `fps` · `tracks`(kind별 element의 `in_ticks`/`out_ticks`/`intended_ticks`는 **정수 틱**, `mode`·
   `transition`). 시간은 초가 아니라 **정수 틱이 진실**(TICKS_PER_SECOND=120000). FFmpeg가 오늘
   실행 가능한 필드만 — GPU 전용(blend_mode·mask·shader uniform) 금지. `python3 check_timeline.py
   validate edit_decisions.json`로 스키마 검증(exit 0 아니면 렌더 금지). 이후 렌더 단계는 이 IR을
   순회한다(출력 로그가 아니라 **에이전트가 저작하는 입력**).
1. **아바타 트랙 결합** → 검증: `avatar/clip-NN.mp4`를 순서대로 concat. 경계가 오디오
   연속과 맞는지(끊김·중복 없음).
2. **그래픽 타임라인** → 검증: 시각 큐별 HyperFrames 블록(`/hyperframes` HTML 렌더)의
   in/out을 타임스탬프에 매핑.
3. **B-roll 배치** → 검증: `[[video-stitch-broll]]` — 생성형 클립을 해당 구간에 삽입(아바타
   노출 규칙과 충돌 없게).
4. **아바타 컴포지팅** → 검증: `[[video-stitch-compositing]]` — 모든 프레임에 아바타 가시,
   둥근 크롭이면 드롭섀도·코너 반경 일관, 전환·여백 프로페셔널.
5. **자막** → 검증: `[[video-stitch-captions]]` — 동기 자막 번인(화면 텍스트는 검증 4관문 대상).
6. **음악 믹스·마스터 렌더** → 검증: `[[audio-post]]`의 음악 베드를 나레이션 아래로 덕킹
   믹스 + 오디오·영상 트랙을 `final/video.mp4`로 렌더. 해상도·fps·싱크 일관.

## 출력 계약

**정전 입력** `edit_decisions.json`(에이전트 저작 IR — `schemas/edit_decisions.schema.json` 준수)을
렌더해 **`final/video.mp4`** + **`final/timeline.json`**(이 IR의 *파생 렌더-리포트* — 동일 스키마로
실제 렌더된 in/out·모드를 기록, 검증 대조 기준)을 낸다. 두 문서 모두 `check_timeline.py validate`
통과해야 한다(이름 정전화: `edit_decisions.json`=정전 저작 입력 · `final/timeline.json`=그 파생
렌더-리포트 — 동일 IR 스키마). 상위 `[[youtube-video-pipeline]]`로 반환 → `[[video-verify]]` 입력
(타이밍 게이트=`check_timeline.py check`).
