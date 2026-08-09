---
name: heygen-avatar-render-gate
description: HeyGen 아바타 렌더의 적격성·완결성 게이트 하위 스킬 — 아바타 look의 supported_api_engines로 avatar_v 적격 확인, 렌더 폴링 재시도 정책, 립싱크·길이·완결 QC를 담당한다. heygen-avatar-render 품질 관문. "아바타 적격성 / 렌더 QC / 립싱크 검수" 맥락에서 발동.
---

# heygen-avatar-render-gate

생성 호출이 "성공"이라고 끝나도 영상이 쓸 만한지는 별개다. 이 게이트가 적격성과 완결성을 막는다.

## 적격성 (생성 전)

1. **엔진 지원 확인** → 검증: 쓰려는 아바타 look의 `supported_api_engines`에 `avatar_v`가
   있는지 확인. 없으면 (a) `avatar_v` 지원 look으로 교체하거나 (b) `avatar_iv`로 폴백(품질
   트레이드오프 명시). **"studio 전용 제약" 같은 건 없다** — 단지 look별 적격 플래그다.
2. **플랜 확인** → 검증: 첫 호출이 플랜 미달로 거부되면(Pro/Scale 필요·무료 티어 없음) 그
   응답을 그대로 사용자에게 안내하고 멈춘다(추측·우회 금지).

## 완결성 (생성 후)

3. **폴링 재시도** → 검증: `generating`이 비정상적으로 길거나 `failed`면 지수 백오프로 N회
   재시도(상한 명시). 매 시도·사유를 기록.
4. **립싱크·길이 QC** → 검증: 다운로드한 클립 길이가 입력 오디오 길이와 일치하는가(잘림·
   누락 없음). 첫·끝 프레임에 아바타가 정상 노출되는가. 명백한 립싱크 실패(입 안 움직임)
   샘플 점검.

## 출력 계약

게이트 판정 `{eligible, rendered, lipsync_ok}` 와 사유. 전부 통과해야 상위
`[[heygen-avatar-render]]`가 그 클립을 합격 처리. 미통과 클립은 재렌더 대상으로 표시하고
원인(적격성/플랜/렌더실패/립싱크)을 보고한다.
