---
name: youtube-video-pipeline
description: 주제 한 문장 → 완성된 유튜브 영상(아바타 + 모션그래픽 + 생성형 B-roll + 음악 + 썸네일)을 end-to-end로 자동 제작하는 대표 오케스트레이터 스킬. 대본→음성→아바타→생성형 비주얼→모션그래픽→음악→합성→검증의 기둥을 순서대로 굴린다. "유튜브 영상 만들어 / AI 영상 자동 제작 / 아바타 영상 파이프라인 / make a youtube video / hyperframes avatar video" 트리거, 또는 /goal 이 영상 제작 목표를 받을 때 발동.
---

# youtube-video-pipeline

주제 한 문장에서 업로드 가능한 유튜브 영상까지 — 사람 편집자가 만든 것처럼 보이는 결과물을
결정론적 파이프라인으로 만든다. 이 스킬은 **오케스트레이터**다: 직접 일하지 않고 기둥 스킬과
채택한 공식 벤더 스킬(HyperFrames·ElevenLabs·HeyGen·fal)을 정해진 순서로 호출하고, 단계
사이의 게이트를 강제한다.

원본 레퍼런스 워크플로우(HeyGen + HyperFrames + ElevenLabs + fal.ai + Claude Code)를 ezer
환경에 이식하되 **실측으로 정정**했다(60초 청크·playwright 업그레이드는 구식 — VIDEO_CREATOR.md).
핵심 원칙: **각 단계는 검증 게이트를 통과해야 다음으로 넘어간다** — "100% 확신할 때만 멈춘다"는
목표(평판 리스크)를 단계별 기계 게이트로 환원한다.

## 선결 조건 (시작 전 확인)

1. **런타임 키** — `ELEVENLABS_API_KEY`·`HEYGEN_API_KEY`·`FAL_KEY`. 없으면 해당 기둥이
   deny-by-default로 멈추고 정확히 안내(하드코딩 금지·보급용 전제 — `[[suite-runtime-keys]]`).
   유료 호출은 전부 `[[cost-preview-confirm]]`로 사전 비용 확인.
2. **도구** — Node.js 22+, FFmpeg(HyperFrames 요구), Python 3.
3. **공식 벤더 스킬** — HyperFrames 15종(`npx skills add heygen-com/hyperframes`)·ElevenLabs·
   HeyGen·fal MCP. preflight C26이 검증·설치한다(VIDEO_CREATOR.md).

## 파이프라인 (기둥 순서 · 각 단계 → 게이트)

```
1. script-writer          → 게이트: factcheck 전 문장 출처 검증 통과
2. voice-clone-elevenlabs → 게이트: stitching 연속성·경계 음질 QC 통과
3. heygen-avatar-render   → 게이트: Avatar V 엔진 + 립싱크·렌더 완결 통과
4. media-gen (B-roll)     → 게이트: 생성형 비주얼 품질·비용 확인 (3과 병행 가능)
   audio-post (음악)       → 게이트: 라이선스 안전·덕킹 믹스 (병행 가능)
   /hyperframes            ← 모션그래픽·카드는 HyperFrames 공식 스킬로 작성
5. video-stitch           → 게이트: 아바타·그래픽·B-roll·자막·음악 정합 합성
6. video-verify           → 게이트: 시각·타이밍·오디오싱크·사실성 4관문 전부 GO
   media-gen-thumbnail     ← 썸네일(부가 산출물)
```

세부:
1. **대본** — `[[script-writer]]`. 2~4분, 사실 기반. 산출 `script.md`·`script.chunks.json`.
2. **음성** — `[[voice-clone-elevenlabs]]`. 세그먼트별 나레이션 + 문자 타임스탬프. request
   stitching으로 프로소디 연속(원본 "60초 청크"는 구식 — 정정). 산출 `audio/seg-NN.mp3`.
3. **아바타** — `[[heygen-avatar-render]]`. **"avatar 5" = Avatar V**: HeyGen v3 API
   `engine:{"type":"avatar_v"}` + `audio_asset_id` 직접 구동(playwright 폴백 obsolete·미사용).
   산출 `avatar/clip-NN.mp4`.
4. **생성형 비주얼·음악·모션그래픽**(아바타와 병행 가능):
   - `[[media-gen]]` — 시각 큐의 생성형 비주얼(시네마틱 B-roll·이미지)을 fal.ai로. 산출 `media/`.
   - `[[audio-post]]` — 저작권 안전 음악 베드 + 덕킹 믹스 사양. 산출 `audio/music-bed.mp3`.
   - **HyperFrames 공식 `/hyperframes`** — 차트·키네틱 텍스트·카드를 HTML로 렌더.
5. **합성** — `[[video-stitch]]`. 아바타 + 모션그래픽 + B-roll + 자막 + 음악을 하나로 편집
   ("아바타 항상 노출" 규칙 강제). 산출 `final/video.mp4`.
6. **검증** — `[[video-verify]]`. 프레임 추출 + 비전 검수. 한 관문이라도 NO_GO면 원인 단계로
   되돌려 수정→재검증(루프). 4관문 전부 GO일 때만 종료. + `[[media-gen-thumbnail]]`로 썸네일.
   산출 `final/video.mp4`(승인) + `verify-report.md` + `media/thumbnail.*`.

## 오케스트레이션 규칙

- **순서 고정·게이트 강제**: 앞 단계 산출물·게이트 통과 없이 다음 단계 호출 금지(단 4번
  내부 B-roll·음악·모션그래픽은 서로 병행 가능 — 아바타와도 병행).
- **실패 시 되돌림**: 검증에서 잡힌 결함은 원인 단계로 되돌려 고친다(다듬기로 덮지 않는다).
- **사실성 최우선**: `[[script-writer-factcheck]]`(대본)와 `[[video-verify-final-gate]]`(화면
  텍스트)가 이중으로 사실성을 막는다 — 둘 다 통과 못 하면 출고 금지.
- **비용 거버넌스**: 유료 단계(음성·아바타·생성형·업스케일)는 `[[cost-preview-confirm]]`로
  사전 확인·세션 누적 추적. 종료 보고에 총비용 포함. 실지출은 `media/manifest.jsonl` 원장
  합산(`python3 ${EZER_PACK_DIR:-$HOME/.ezer/pack}/bin/check_manifest.py total-cost`)으로 결정론
  산출해 단계 전환·종료 보고에 병기한다. 중단 후 재실행 시 체크포인트 규약 덕에 기생성
  산출물은 자동 생략(RESULT=skipped)됨을 시작 보고에 명시한다.
- **task_progress 방출**: 기둥 1~6 전환 시 `[EVT v2] task_progress`(task·stage·pct·cost_usd_cum)
  를 `ezer_event.py emit`으로 방출한다(EVENT_CONTRACT v2). 단계 전환 시에만 — 폴링·주기
  방출 금지. HUD·음성 에제르의 구독 소스.
- **서사 모드 인지**: 시작 시 `entity_registry.json` 유무를 보고한다. 존재하면 1단계
  `[[script-writer]]` 진입 전에 registry 검증(`check_entity_registry.py validate` exit 0)을
  수행하고, 4단계 media-gen 계열이 [서사 모드] 단계를 수행함을 게이트에 포함한다. 부재
  시(기본) 전 단계는 기존 그대로다.
- **/goal 연동**: `/goal`이 이 스킬을 호출하면 위 단계가 곧 goal의 하위 목표가 된다.

## 출력 계약

종료 시 보고: `final/video.mp4` 경로·길이 · 4관문 결과(전부 GO) · 대본 사실성 요약 ·
사용 모델(아바타·음성·생성형)·HyperFrames 블록 · 세션 총비용 · `media/thumbnail.*`. 한
관문이라도 미통과면 종료하지 말고 원인 단계로 되돌린다.
