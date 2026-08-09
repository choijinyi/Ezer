---
name: heygen-avatar-render
description: ElevenLabs 나레이션 오디오를 HeyGen Avatar V로 말하는 아바타 영상으로 렌더하는 대표 스킬 — 오디오 자산 업로드, v3 API의 avatar_v 엔진·audio_asset_id 구동, 적격성 확인, 폴링·다운로드·립싱크 QC. "아바타 영상 / heygen 렌더 / avatar 5 / talking avatar" 트리거, 또는 youtube-video-pipeline 3단계로 발동.
---

# heygen-avatar-render

나레이션 오디오를 받아 말하는 아바타 영상을 만든다. 우리 파이프라인은 **오디오 우선**
(ElevenLabs로 음성을 먼저 만든다) — HeyGen은 그 오디오로 립싱크만 한다.

> ★실측 정정(2026): 원본의 "API로 avatar 5를 못 써서 playwright로 업그레이드"는 **obsolete**다.
> "avatar 5" = **Avatar V**(로마숫자 V)이고, 2026-05 Avatar IV/V API 출시 이후 **공개 v3
> API로 직접 선택 가능**하다(`engine:{"type":"avatar_v"}`). 따라서 playwright 폴백은 만들지
> 않는다 — 단순성·정확성 원칙. (출처: HeyGen Avatar IV API 발표 2026-05-04)

## 키·플랜·도구

- 키: `HEYGEN_API_KEY`(런타임 — `[[suite-runtime-keys]]`, 없으면 deny-by-default). base
  `https://api.heygen.com`, auth 헤더 `x-api-key`. 키 발급: app.heygen.com/api.
- **플랜 게이트**: Avatar IV/V API는 Pro/Scale 셀프서브(Enterprise 커스텀), **무료 티어 없음**
  (~$4/분 1080p 수준, 지표값). 키가 있어도 플랜 미달이면 API가 거부 — 그 응답을 그대로 안내.
- 공식 스킬 참고: `github.com/heygen-com/skills`의 `heygen-video`는 **스크립트 구동**(Video
  Agent)이라 오디오 구동 경로가 없다 — 우리는 `POST /v3/videos` + `audio_asset_id`를 직접
  쓴다. `heygen-avatar`(디지털 트윈 생성)는 아바타·음성 셋업 시 참고.

## 하위 스킬 오케스트레이션

1. `[[heygen-avatar-render-api]]` — 오디오 업로드 → v3 생성(avatar_v·audio_asset_id) → 폴링 → 다운로드.
2. `[[heygen-avatar-render-gate]]` — 아바타 look의 `supported_api_engines` 적격성 + 폴링 재시도 +
   립싱크/렌더 완결 QC.

## 절차

1. **아바타 적격성** → 검증: `[[heygen-avatar-render-gate]]` — 쓸 아바타 look이
   `supported_api_engines`에 `avatar_v`를 포함하는지 확인(없으면 적격 look 선택 또는 avatar_iv).
2. **세그먼트별 렌더** → 검증: 각 `audio/seg-NN.mp3`에 대해 `[[heygen-avatar-render-api]]` 호출.
   audio 우선(`audio_asset_id`) — `script`와 상호배타. engine=avatar_v.
3. **완결 QC** → 검증: 각 클립이 `completed` 상태로 끝나고 영상이 다운로드됐는지, 길이가
   오디오 길이와 일치하는지(립싱크 누락·잘림 없음).

## ★출시 전 1회 실측 확인 (환각 방지)

audio 필드의 정확한 JSON 위치가 v3 reference(요청 본문 최상위)와 레거시 문서(voice
객체 `type:"audio"`)에서 다르다. **첫 실호출 1건의 응답으로 정확한 스키마를 고정**한 뒤
하드코딩하라. v1/v2 경로(`/v2/video/generate` 등)는 deprecated — 쓰지 말 것.

## 출력 계약

`avatar/clip-NN.mp4`(세그먼트별, 오디오 길이와 일치) + `avatar/render-manifest.json`
(video_id·engine·avatar_id·status). 전 클립 completed·다운로드 완료해야 상위
`[[youtube-video-pipeline]]`가 합성 단계로 진행.
