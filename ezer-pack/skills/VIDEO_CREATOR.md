# ezer-video-creator — 영상 자동제작 스킬 묶음 (ezer 기본 탑재)

주제 한 문장 → 업로드 가능한 유튜브 영상(말하는 아바타 + 모션그래픽 + 생성형 B-roll + 음악
+ 썸네일)을 end-to-end로 자동 제작하는 Claude Code 스킬 묶음. 사람 편집자가 만든 것처럼 보이는
결과물을 **결정론적 파이프라인 + 단계별 검증 게이트**로 만든다.

ezer pack에 임베드돼 모든 머신에 기본 배포되고(바이너리 동봉), preflight **C26**이
네이티브 Claude Code(/goal) 발견을 위해 프로필 skills/ 로 심링크한다.

## 아키텍처 — 대표 7기둥 + 하위 (우리 제작 32종 + 공식 벤더 채택)

오케스트레이터 `youtube-video-pipeline`이 기둥을 순서대로 굴리고 단계 사이 게이트를 강제한다.

| # | 대표 스킬 | 하위 스킬 | 제작/채택 |
|---|---|---|---|
| 1 | `script-writer` | research·structure·factcheck·voice-prep | 제작(rep+4) |
| 2 | `voice-clone-elevenlabs` | chunk·synth-qc | 제작(rep+2) |
| 3 | `heygen-avatar-render` | api·gate | 제작(rep+2) |
| 4 | `media-gen` (생성형 B-roll·이미지) | image·edit·video·upscale·thumbnail | 제작(rep+5) |
| 5 | `video-stitch` (편집·합성) | compositing·broll·captions | 제작(rep+3) |
| 6 | `audio-post` (음악·믹스) | music·mix | 제작(rep+2) |
| 7 | `video-verify` | visual·timing·audio-sync·final-gate | 제작(rep+4) |
| — | **HyperFrames 모션그래픽** | (공식 15종) | **채택** `npx skills add heygen-com/hyperframes` |

공통 규약: `suite-runtime-keys`(키 런타임 입력·deny-by-default) · `cost-preview-confirm`(유료
호출 사전 비용 확인) · 오케스트레이터 `youtube-video-pipeline`. **우리 제작 32종.**

운영 기법(레퍼런스 영상에서 채택, 전 기둥 소급): ①유료 호출 전 비용 미리보기+확인
②API 제한 자기교정 후 재시도 ③거친 의도→모델 최적 프롬프트 재작성.

## 통합 (ezer 기본 탑재)

- **배포**: `ezer-pack/skills/`에 임베드(단일 진실원천) → build.rs 자동 임베드 → 데몬이
  `~/.ezer/pack/skills`에 설치 → ezer 노드는 디렉티브 색인 주입으로 발견.
- **C26 preflight**(비차단·옵트인 능력): 기계(`--fix`)가 우리 32종을 프로필로 심링크 +
  공식 벤더 스킬 설치(HyperFrames·ElevenLabs) + Node22/FFmpeg 점검. API 키는 사람 단계 WARN.

## 선결 조건 (영상 제작 시)

- **런타임 키**(보급용 — 하드코딩 안 함): `ELEVENLABS_API_KEY`·`HEYGEN_API_KEY`·`FAL_KEY`.
  없으면 해당 단계가 deny-by-default로 멈추고 정확히 안내(C26 WARN).
- **도구**: Node.js 22+, FFmpeg(HyperFrames 요구), Python 3.
- **플랜**: HeyGen Avatar IV/V API는 Pro/Scale 셀프서브(무료 티어 없음) · fal.ai 프리페이드 크레딧.

## 사용

```
/youtube-video-pipeline  "Claude Fable 5 출시와 강점을 설명하는 2~4분 영상"
```
또는 `/goal`에게 영상 제작 목표를 주면 이 파이프라인이 하위 목표가 된다.

---

# 채택한 공식 벤더 스킬 · 출처 · 실측 근거

raw API 기계·모션그래픽은 **벤더 공식 자산**을 채택하고(재제작 금지·드리프트 방지), 우리
스킬은 그 위에 *파이프라인 정책*(올바른 청킹·stitching·비용 가드·검증 게이트·합성 규칙)을 얹는다.

## HyperFrames (모션그래픽)
- HeyGen 오픈소스(Apache 2.0) "HTML→영상" 프레임워크. HTML/CSS/JS → 헤드리스 브라우저
  프레임 캡처 → FFmpeg MP4. 공식 스킬 15종 `npx skills add heygen-com/hyperframes`. CLI
  `npx hyperframes init|preview|render`. 출처: github.com/heygen-com/hyperframes · hyperframes.heygen.com

## ElevenLabs (음성)
- 공식 스킬 `npx skills add elevenlabs/skills`(`text-to-speech`·`setup-api-key`) · MCP
  `elevenlabs/elevenlabs-mcp`. raw 합성은 위임, 우리 계열은 정책(문장경계·글자한도 청킹·
  **request stitching**·잠금 settings/seed·with-timestamps).
- ★정정 근거: 원본 "60초 청크"는 **구식** — 제한 축은 글자수(multilingual_v2=10,000), 청크
  프로소디 점프 해법은 stitching(2024+). 출처: elevenlabs.io/docs/cookbooks/.../request-stitching

## HeyGen 아바타
- 공식 스킬 `gh skill install heygen-com/skills <name>`(avatar·video·translate). 단 `heygen-video`는
  스크립트 구동이라 우리 **오디오 우선** 경로와 안 맞아 `POST /v3/videos`+`audio_asset_id` 직접 호출.
- ★정정 근거: "avatar 5"=**Avatar V**(로마숫자). 2026-04 Avatar V·2026-05 Avatar IV API 출시
  이후 v3 API로 직접 선택(`engine:{"type":"avatar_v"}`). "playwright 업그레이드"는 web-only
  시절 잔재로 **obsolete·미구현**. audio 필드 JSON 위치는 첫 실호출로 고정 권고. 플랜 Pro/Scale·
  무료 티어 없음. 출처: developers.heygen.com/reference/create-video · heygen.com/blog/announcing-the-avatar-iv-api

## fal.ai (생성형 비주얼 — 4번 기둥)
- 이미지·영상 모델 애그리게이터. 키 `FAL_KEY`(헤더 `Authorization: Key`). 큐 `queue.fal.run`,
  모델은 경로(`fal-ai/nano-banana-pro`·`.../edit`·`fal-ai/kling-video/.../image-to-video`·
  `bytedance/seedance-2.0/image-to-video`·`fal-ai/topaz/upscale/video`). 표준 루프 업로드→제출→
  폴링→다운로드. **새 모델=경로만 교체**. 공식 MCP `mcp.fal.ai/mcp`·SDK `@fal-ai/client`/`fal-client`·
  커뮤니티 스킬 `fal-ai-community/skills`. 사전 비용추산 API `POST api.fal.ai/v1/models/pricing/estimate`.
  스키마는 모델별 상이 → 런타임 조회(하드코딩 금지). 출처: fal.ai/docs · fal.ai/models

## 라이선스
HyperFrames=Apache 2.0(HeyGen) · HeyGen skills=MIT · ElevenLabs skills=해당 레포 · fal 커뮤니티
스킬=MIT. 벤더 자산은 vendoring하지 않고 공식 채널 설치(C26·드리프트 방지). 조사 2026-06-13.
