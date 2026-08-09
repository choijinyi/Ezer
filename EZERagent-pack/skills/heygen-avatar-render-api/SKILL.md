---
name: heygen-avatar-render-api
description: HeyGen v3 API로 오디오 구동 아바타 영상을 생성하는 하위 스킬 — 오디오 자산 업로드, POST /v3/videos(engine avatar_v + audio_asset_id), 상태 폴링, 결과 다운로드의 canonical 호출 절차. heygen-avatar-render 실행 코어. "heygen v3 호출 / 아바타 영상 생성 / audio_asset_id" 맥락에서 발동.
---

# heygen-avatar-render-api

HeyGen v3의 오디오 구동 생성 호출을 수행한다. 검증된 canonical 형태(2026):

## 호출 흐름

1. **오디오 업로드** → 검증: `audio/seg-NN.mp3`를 HeyGen 자산으로 업로드해 `audio_asset_id`를
   얻는다(또는 공개 URL이 있으면 `audio_url` 사용 — 둘은 상호배타, 정확히 하나).
   ★비용 가드: 렌더는 분당 종량제 — 생성 전 `[[cost-preview-confirm]]`(분량×해상도 단가)로
   예상 비용 확인·세션 누적 기록.
2. **영상 생성** → 검증: `POST https://api.heygen.com/v3/videos`, 헤더 `x-api-key: $HEYGEN_API_KEY`.
   본문 핵심:
   - `engine: {"type": "avatar_v"}` (생략 시 기본 `avatar_iv`)
   - 아바타 지정(avatar look id) + **`audio_asset_id`**(또는 `audio_url`) — `script`와 상호배타
   - 해상도·배경 등 옵션
   *audio 필드의 정확한 위치(최상위 vs voice 객체 `type:"audio"`)는 버전차가 있으니 첫
   실호출 응답으로 스키마를 고정한 뒤 박는다.*
3. **폴링·자기교정** → 검증: 상태 흐름 `thinking → generating → completed | failed`. 완료까지
   폴링(지수 백오프). `failed`면 사유를 읽고 교정 가능한 제약(입력 포맷·길이·자산)이면 자동
   교정 후 재시도, 아니면 그대로 보고. 재시도 상한·정책은 `[[heygen-avatar-render-gate]]`에 위임.
4. **다운로드** → 검증: completed 응답의 `video_url`(S3 MP4)을 `avatar/clip-NN.mp4`로 저장.

## 금지

- v1/v2 경로(`/v2/video/generate`·`use_avatar_iv_model` 등) — deprecated, 쓰지 말 것.
- 키 하드코딩·로깅 — `[[suite-runtime-keys]]` 규약.
- 학습지식으로 스키마 단정 — 첫 실호출로 검증 후 고정.

## 출력 계약

`avatar/clip-NN.mp4` + 해당 항목의 `{video_id, engine, avatar_id, status, video_url}`를
`avatar/render-manifest.json`에 누적. 상위 `[[heygen-avatar-render]]`로 반환.
