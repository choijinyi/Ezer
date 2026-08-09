---
name: media-gen
description: fal.ai 애그리게이터로 생성형 비주얼을 만드는 대표 스킬 — 텍스트→이미지·참조 편집·이미지→영상(시네마틱 B-roll)·업스케일·썸네일을 하위 스킬로 오케스트레이션한다. 모델을 경로로 지정해 새 모델도 코드 변경 없이 채택. "이미지 생성 / B-roll 생성 / 영상 생성 / 업스케일 / 썸네일 / fal" 트리거, 또는 youtube-video-pipeline B-roll 단계로 발동.
---

# media-gen

아바타·HTML 모션그래픽으론 못 만드는 **생성형 비주얼**(포토리얼 장면·시네마틱 B-roll·생성
이미지·썸네일)을 만든다. 단일 게이트웨이는 **fal.ai** — 이미지·영상 모델 애그리게이터다.

## 아키텍처 (fal.ai 실측 기반)

- **키**: `FAL_KEY`(런타임 — `[[suite-runtime-keys]]`, 없으면 deny-by-default). 헤더는
  `Authorization: Key $FAL_KEY`(Bearer 아님). 큐 base `https://queue.fal.run`, 동기 `https://fal.run`.
- **애그리게이터 패턴**: 모델은 **경로**로 지정한다(`fal-ai/nano-banana-pro`,
  `fal-ai/kling-video/.../image-to-video`, `bytedance/seedance-2.0/image-to-video`,
  `fal-ai/topaz/upscale/video`). **새 모델 = 경로만 바꾸면 됨 — 통합 코드 불변**(미래 내성).
- **표준 루프**: 로컬 입력 업로드(`fal_client.upload_file` → `v3.fal.media` URL) → `POST
  {model_id}` → 상태 폴링 → 결과 GET → 출력 URL HTTP GET. 입력 이미지는 URL로 전달
  (`image_urls` 배열=편집, `image_url`=영상).
- **스키마 하드코딩 금지**: 모델마다 파라미터가 다르다(nano-banana-pro=`aspect_ratio`+
  `resolution`, flux=`image_size`, topaz=`upscale_factor` 배율). **런타임에 라이브 스키마 조회**
  (공식 MCP `get schema` 또는 모델 `/api` 페이지) 후 호출.
- **공식 자산 채택**: 공식 MCP `https://mcp.fal.ai/mcp`(모델 검색·스키마·가격·실행 도구) ·
  SDK `@fal-ai/client`/`fal-client` · 커뮤니티 스킬 `fal-ai-community/skills`(genmedia). raw
  호출 기계는 이들에 위임하고, 우리 스킬은 *파이프라인 정책*(프롬프트 재작성·비용·자기교정)을 얹는다.

## 하위 스킬 오케스트레이션

1. `[[media-gen-image]]` — 텍스트→이미지(프롬프트 재작성·모델 선택).
2. `[[media-gen-edit]]` — 참조/편집(정체성 보존, `image_urls`).
3. `[[media-gen-video]]` — 이미지→영상 시네마틱 B-roll(길이·초당 비용).
4. `[[media-gen-upscale]]` — 영상/이미지 업스케일(Topaz).
5. `[[media-gen-thumbnail]]` — 클릭 유도 썸네일(이미지 + 텍스트 오버레이).

## 공통 운영 기법 (전 하위 스킬 적용)

- **프롬프트 재작성**: 사용자의 거친 의도를 *모델 최적 프롬프트*로 Claude가 재작성 후 생성.
- **비용 가드**: 유료 호출 전 `[[cost-preview-confirm]]`(fal 공식 추산 API
  `POST https://api.fal.ai/v1/models/pricing/estimate` 활용 가능) — 영상·업스케일은 종량제.
- **자기교정**: API 제한 감지 시 자동 교정 후 재시도(예: 입력 이미지 용량 초과 → 압축 →
  재실행. Seedance 입력 30MB 한도 등 모델별 제약을 응답에서 읽고 대응).
- **로컬 저장**: 산출물을 `media/` 하위에 파일경로로 저장(이미지·B-roll·썸네일 분류).
- **체크포인트·비용 원장**: 유료 호출 직전 `media/manifest.jsonl` 대조 —
  `python3 ${EZERAGENT_PACK_DIR:-$HOME/.EZERagent/pack}/bin/check_manifest.py check` exit 0(산출물 실존 ∧
  동일 입력해시 ok 레코드)이면 생략(RESULT=skipped). 생성 결과는 `record`로 append(append-only
  — 재실행 절약과 실지출 결정론 산출의 단일 원장, 계약=media-gen 폴더 `MANIFEST_CHECKPOINT_CONTRACT.md`).
- **서사 모드(opt-in)**: 프로젝트 루트에 `entity_registry.json`이 존재할 때만 하위 스킬들의
  [서사 모드] 단계(초상·참조 선택·last-frame 조건)가 발동한다. 없으면 전 하위 스킬은 기존
  그대로 동작한다.

## 출력 계약

`media/broll/*.mp4`·`media/images/*`·`media/thumbnail.*` + `media/manifest.jsonl`
(append-only 원장: 작업·모델경로·프롬프트 해시·seed·실비용 — 구 `gen-manifest.json` 명명을
이 원장으로 통일). 상위 `[[youtube-video-pipeline]]`로 반환 →
B-roll은 `[[video-stitch-broll]]`이 배치, 썸네일은 별도 업로드 산출물.
