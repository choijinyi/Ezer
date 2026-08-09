---
name: video-verify-timing
description: 모션그래픽의 진입·퇴장 타이밍이 나레이션·타임라인과 정확히 맞는지 검증하는 하위 스킬 — 그래픽이 해당 발화 지점에 맞춰 들어오고 나가는지, 너무 이르거나 늦지 않은지 판정한다. video-verify 2관문. "타이밍 검증 / 모션 싱크 / 그래픽 진입 점검" 맥락에서 발동.
---

# video-verify-timing

"모션그래픽이 제때 들어온다"는 원본 요구를 기계로 검증한다. 그래픽이 말과 어긋나면
아마추어처럼 보인다.

## 기준

- `final/timeline.json`(각 그래픽·아바타 모드의 in/out)과 `audio/timestamps.json`(문자 정렬),
  `outline.md`의 시각 큐가 정합 기준이다.
- 각 그래픽은 그 그래픽이 설명하는 발화 구간에 **맞춰** 진입해야 한다(통상 해당 키워드
  발화 직전~직후 짧은 창). 너무 이르면 스포일, 너무 늦으면 헛돈다.

## 절차

1. **결정론 타이밍 게이트(권위)** → 검증: 팩 동봉 `bin/check_timeline.py`로 각 그래픽의
   intended↔실제 in 드리프트를 **정수-틱 프레임 격자**(TICKS_PER_SECOND=120000)에서 판정한다.
   `python3 check_timeline.py check final/timeline.json --probe final/video.mp4 [--fps N] --json`.
   exit 0=GO · 1=NO_GO(드리프트 초과 그래픽 + 틱/프레임 단위 차이) · 2=입력오류(표현 불가
   프레임레이트·timeline 계약 미준수 등 — **fail-loud**, 조용한 통과 없음). 타이밍 합/불은 이
   게이트가 **권위**를 갖는다(LLM 부동소수 ±0.3초 눈대중 대체). 허용 오차 기본 ±0.3초 보존
   (`--tolerance-frames`로 프레임 단위 강화 가능).
2. **시각 확인(비전 — 타이밍 아님)** → 검증: 진입/퇴장 프레임을 비전으로 보되 *시각* 결함만
   판정한다 — 잘린 진입·갑작스런 컷·퇴장 누락(화면 잔존). 진입 *시점*의 합/불은 1의 결정론
   게이트 소관이다(이중 판정 금지).
3. **집계** → 검증: 1(타이밍 게이트 GO) ∧ 2(시각 결함 없음)이면 GO. 아니면 NO_GO + 어긋난
   그래픽·시각(1의 issues + 2의 시각 플래그). 1의 exit 2(입력오류)는 검증 불능이므로 GO 선언 금지.

## 렌더 충실도 replay-verify (추가적·조건부 — W2-3)

선언된 편집-결정 IR(`edit_decisions.json`)의 컷 경계가 **실제 렌더된 영상에 그대로 나타났는가**를
결정론으로 단언하는 *두 번째* 게이트(절차 1의 나레이션-싱크를 대체하지 않고 *추가*한다).

```bash
ffprobe -v error -select_streams v -show_packets -show_entries packet=pts_time,flags \
  -of json final/video.mp4   # keyframe(flags=K) PTS를 measured_seconds로
python3 check_timeline.py boundaries --input boundaries.json --fps <N> --tolerance-frames 1
# boundaries.json = {"fps":N,"declared_ticks":[IR 컷 경계],"measured_seconds":[측정 keyframe PTS]}
```

- **조건부 전제**: 렌더가 IR로부터 *프레임-결정적*이어야 유효하다 — 그렇지 않으면 이 단언은
  보류한다(W0-1 정수-틱 + W0-2 IR이 선행 의존). frame-equality는 **keyframe-강제 컷 지점에만**
  적용(P/B-프레임 PTS는 코덱/컨테이너 의존 → 오탐). 그 외 구간은 scene-change 허용오차로.
- 출력 `{gate:"render_fidelity", verdict, mismatches:[{declared_ticks, nearest_measured_ticks, frame_delta}]}`
  를 절차 1의 타이밍 verdict와 **별개 이슈 타입**으로 함께 반환(final-gate는 둘 다 소비).
- ffprobe는 팩 전제(미설치면 이 단언만 건너뛰고 절차 1·2는 진행).

## 출력 계약

`{gate: "timing", verdict: GO|NO_GO, issues: [{graphic_id, intended, actual, drift}]}`
(check_timeline.py는 여기에 `drift_ticks`·`drift_frames`·`fps_rational`·`ticks_per_frame`를
추가로 실어 결정론 근거를 남긴다 — 상위 계약과 호환). 상위 `[[video-verify]]`로 반환.
NO_GO면 원인 단계(`[[video-stitch]]` 타임라인)로 회송.
