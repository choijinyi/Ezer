---
name: video-stitch-broll
description: media-gen이 생성한 B-roll(이미지·영상 클립)을 편집 타임라인의 적소에 배치하는 하위 스킬 — 시각 큐에 맞춰 삽입하고 아바타 노출 규칙·길이·전환과 충돌 없게 조율한다. video-stitch B-roll 관문. "B-roll 배치 / 생성 클립 삽입 / 보조영상 편집" 맥락에서 발동.
---

# video-stitch-broll

`[[media-gen]]`이 만든 생성형 비주얼(시네마틱 클립·생성 이미지)을 본 영상에 끼워 넣는다.
B-roll은 설명을 *보여주는* 장치 — 말과 어긋나거나 아바타를 가리면 역효과다.

## 절차

1. **큐 매핑** → 검증: `outline.md`의 시각 큐 중 "생성형 비주얼" 항목을 `media/broll/`의
   해당 클립과 매핑. 각 B-roll의 in/out을 발화 타임스탬프에 맞춘다.
2. **아바타 규칙 조율** → 검증: B-roll 구간에서도 아바타가 보이게(`[[video-stitch-compositing]]`
   (b) 둥근 크롭 PIP 권장). 풀스크린 B-roll로 아바타가 사라지지 않게.
3. **길이·전환** → 검증: B-roll 클립 길이가 발화 구간을 넘거나 모자라지 않게(필요시 trim/loop).
   진입·퇴장 전환이 갑작스럽지 않게.
4. **품질 게이트** → 검증: B-roll 해상도·프레임레이트가 본 영상과 정합(저해상 삽입 금지).

## 출력 계약

B-roll이 배치된 타임라인 + `final/timeline.json`에 각 B-roll의 클립·in/out·구간 모드 기록.
상위 `[[video-stitch]]`로 반환. 미스싱크·아바타 가림은 보고·수정.
