---
name: script-writer
description: 영상 주제 한 문장 → 사실 기반의 2~4분 유튜브 나레이션 대본을 만드는 대표 스킬. 리서치→구조 설계→사실검증→음성 청크 분절 4단계를 하위 스킬로 오케스트레이션한다. "영상 대본 / 스크립트 작성 / 나레이션 대본 / youtube script" 트리거, 또는 youtube-video-pipeline 1단계로 발동.
---

# script-writer

영상의 토대는 대본이다. 토대가 사실 아니면 뒤의 음성·아바타·모션그래픽이 아무리 좋아도
거짓을 정교하게 포장할 뿐이다(평판 리스크의 진원). 이 스킬은 대본을 **리서치→구조→
사실검증→음성준비**의 4관문으로 통과시키는 대표 스킬이다.

## 하위 스킬 오케스트레이션 (순서)

1. `[[script-writer-research]]` — 주제의 검증된 사실·출처를 수집한다(학습지식 단독 금지).
2. `[[script-writer-structure]]` — 훅·본론·CTA로 2~4분 리텐션 구조를 설계한다.
3. `[[script-writer-factcheck]]` — 모든 단정 문장을 출처 대조로 검증한다(`hallucination-guard` 연결).
4. `[[script-writer-voice-prep]]` — 대본을 ≤60초 음성 청크 경계로 분절한다.

각 하위 스킬은 자체 검증 게이트를 가진다. 한 관문이라도 실패하면 그 관문에서 멈추고
고친 뒤 진행한다.

## 절차

1. **의도 합의** → 검증: 주제·길이·톤·타깃·핵심 메시지를 1줄로 확정. 모호하면
   `grill-me`로 질문해 합의한다. 영상 패키징(예: "Claude Fable 5가 이 영상을 만들었다")을 명시.
2. **리서치** → 검증: `[[script-writer-research]]` 산출 `facts.md`의 모든 항목에 출처 URL/근거.
3. **구조 설계** → 검증: `[[script-writer-structure]]` 산출 `outline.md`가 훅(0~15초)·
   본론(세그먼트)·CTA를 갖추고, 분량이 목표 길이(말하기 속도 기준)에 맞는가.
4. **대본 작성** → 검증: outline을 나레이션 문장으로 확장. 구어체·한 호흡 문장·시각 큐 주석.
5. **사실 검증** → 검증: `[[script-writer-factcheck]]` — 단정 문장 전수 통과. 미검증 문장은
   삭제하거나 출처를 단다. **이 관문 미통과 시 출고 금지.**
6. **음성 준비** → 검증: `[[script-writer-voice-prep]]` 산출 `script.chunks.json`의 각 청크가
   ≤60초이고 자연스러운 경계(문장·구)에서 끊기는가.
7. **[서사 모드] 엔티티 명세 추출(조건부)** → 검증: 대본이 서사형(동일 인물이 2개 이상
   장면에 재등장)이고 사용자가 서사 영상화를 명시 확인한 경우에만 — 인물별 static(불변:
   얼굴·체형·나이대)/dynamic(가변: 의상·소품) 분리 명세와 공간 slugline을 추출해 프로젝트
   루트에 `entity_registry.json`을 생성한다(`python3 ${EZERAGENT_PACK_DIR:-$HOME/.EZERagent/pack}/bin/check_entity_registry.py validate`
   exit 0 — 스키마는 media-gen 스킬 폴더의 `entity_registry.schema.md`). 규율: 동일 실체
   이름 통합·배경 인물 제외·추상어 금지·시각화 가능한 묘사만·성격/역할/관계 서술은
   static/dynamic 어느 쪽에도 금지. 해설형·B-roll형 영상이면 이 단계를 건너뛴다(파일
   미생성 = 하류 전 단계가 기존 그대로 동작).

## 출력 계약

- `script.md` — 섹션별 최종 대본(시각 큐 주석 포함)
- `facts.md` — 사실·출처 대장
- `script.chunks.json` — 음성 청크 배열 `[{id, text, est_seconds, visual_cue}]`
- (서사 모드 한정) `entity_registry.json` — 인물·공간 영속 레지스트리(하류 media-gen·video-verify가 소비)
- 사실 검증 결과 요약(통과/삭제/출처보강 건수). 다음 기둥(`[[voice-clone-elevenlabs]]`)으로
  `script.chunks.json`을 넘긴다.

말하기 속도 기준: 영어 ~150 wpm, 한국어 ~330 음절/분. 2~4분 = 영어 약 300~600단어.
