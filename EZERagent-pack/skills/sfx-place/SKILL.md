---
name: sfx-place
description: 효과음(SFX)을 영상 타임라인의 적절한 지점에 배치하는 대표 스킬 — provider는 하드코딩하지 않고 EZERagent_select로 결정론 선택(무키 로컬 SFX 라이브러리 바닥부터, deny-by-default). 현 audio-post가 BGM(배경음악)만 다룬다면 이 스킬은 *효과음 배치*를 담당한다. "효과음 / SFX / 사운드이펙트 / 효과음 배치 / 휙 효과음 / whoosh / foley / freesound" 트리거, 또는 cinematic·screen-demo 아키타입의 assets 단계로 발동.
EZERagent:
  capability: sfx-place
  stability: beta
  cost_class: light
  best_for: 효과음(SFX)을 타임라인 지점에 결정론 배치 — 트레일러 임팩트·데모 콜아웃 사운드의 토대
---

# sfx-place

영상 타임라인의 **이벤트 지점**(컷·콜아웃·임팩트)에 효과음을 배치한다. `audio-post`가 BGM
(배경음악)을 다룬다면, 이 스킬은 **개별 효과음**(whoosh·click·impact·foley)의 선택·타이밍·게인을
계획한다. cinematic(트레일러 임팩트)·screen-demo(콜아웃 사운드) 2 아키타입이 의존한다.

> ★EZERagent-native(AGPL 클린룸): SFX 배치 흐름을 참고했을 뿐 코드를 복사하지 않는다. 실제 음원은
> 아래에서 결정론 선택한 provider(로컬 라이브러리/Freesound CC)에서 가져온다.

## provider 선택 (하드코딩 금지 — EZERagent_select 위임)

```bash
EZERagent_select rank --catalog "${EZERAGENT_PACK_DIR:-$HOME/.EZERagent/pack}/round/video_provider_catalog.json" \
  --capability sfx-place --intent "<용도: 트레일러임팩트/데모콜아웃>" --free-first
```

- **무료·로컬 바닥**: `sfx_local`(로컬 SFX 라이브러리·무키·결정론). 키가 없어도 항상 가용 —
  효과음 배치는 키 없이 동작한다.
- 더 넓은 라이브러리가 필요하면 `sfx_freesound`(Freesound CC·`FREESOUND_API_KEY` 설정 시 setup_offer로
  안내). `--free-first`로 무료 바닥 우선.

## 입력·산출물 계약

- **입력**: `scene_plan.json`의 `scenes[]`(컷·이벤트 지점) 또는 edit 단계의 콜아웃/임팩트 마커.
- **산출**: `sfx_plan.json`(작업 폴더):

```json
{
  "provider": "<EZERagent_select가 고른 id>",
  "placements": [
    {"at": 3.2, "sfx_id": "whoosh_01", "gain_db": -8.0, "reason": "shot-change impact"}
  ]
}
```

- **`placements[]`가 핵심** — 각 효과음의 `at`(타임라인 위치·소스 경계 안)·`sfx_id`·`gain_db`(BGM/
  내레이션 대비 과하지 않게). 실제 믹스는 `audio-post`(별 단계)가 실행한다 — 이 스킬은 *계획*만.

## 환각0·producer≠evaluator (불가침)

- **라이선스 정직**: `sfx_freesound`는 CC 라이선스·출처를 `placements[].source`에 기록한다(임의 음원
  주장 금지). 로컬 라이브러리는 사용 권한 보유분만.
- **과배치 금지**: 효과음으로 도배하지 마라 — 이벤트 근거(`reason`) 없는 배치는 넣지 않는다.
- 검증은 자가채점하지 않는다 — `video-verify`(별 노드)가 믹스 균형·과배치를 독립 확인한다(D1
  verdict 계약·점수금지).

## 거버넌스 배선

- 위임 티켓 전제: `--requires-skills sfx-place`(D6 자동주입). 흔히 `scene-cut`(이벤트 지점)과 함께.
- 아키타입 매니페스트(D4) assets 단계 success_criteria 예:
  `{"kind":"json_valid"}` + `{"kind":"field_present","value":"placements"}`.
- cost_class=light: 배치 계획은 가벼움(실제 오디오 처리는 audio-post 소관).
