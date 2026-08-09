---
name: media-gen-image
description: 텍스트 설명에서 이미지를 생성하는 하위 스킬 — 사용자의 거친 의도를 모델 최적 프롬프트로 재작성한 뒤 fal.ai 이미지 모델(nano-banana-pro 등)로 생성한다. media-gen 이미지 관문. "이미지 생성 / text to image / 프롬프트 재작성 / nano banana" 맥락에서 발동.
---

# media-gen-image

설명에서 이미지를 만든다. 핵심은 **프롬프트 재작성** — 사용자의 거친 한 줄을 모델이 가장 잘
이해하는 프롬프트로 Claude가 다시 쓴 뒤 생성한다(원본 영상의 핵심 기법).

## 절차

1. **의도 수집** → 검증: 사용자의 대략 의도 + 모델·비율·해상도 선호를 받는다.
2. **프롬프트 재작성** → 검증: 거친 의도를 *모델 최적* 프롬프트로 확장(피사체·스타일·조명·
   구도·디테일). 재작성 결과를 사용자에게 보여주고(투명성) 생성.
3. **모델·파라미터** → 검증: 기본 `fal-ai/nano-banana-pro`(고품질). 라이브 스키마 조회 후
   호출 — 이 모델은 `aspect_ratio`(예: `1:1`,`16:9`) + `resolution`(`1K/2K/4K`) + `output_format`,
   `seed`. **스키마 하드코딩 금지.**
3.5 **[서사 모드 — `entity_registry.json` 존재 시만]** → 검증:
   ① 초상 미생성 캐릭터가 있으면 front(static+dynamic+전역 style)를 먼저 생성하고,
      side/back은 front를 참조 이미지로 `[[media-gen-edit]]`(정체성 보존) 경로로 생성해
      registry의 portraits에 경로·status를 기록한다(16:9 가로·순백 배경·전신 규약).
   ② 키프레임 생성 시 registry의 초상·frame_index에서 참조 이미지 ≤4장을 선택한다 —
      규칙: 등장 캐릭터당 1뷰만 / 동일 공간 anchor_frames 우선 / 직전 프레임 최신 우선.
      참조가 1장 이상이면 text-to-image가 아니라 `[[media-gen-edit]]` 경로로 생성하고,
      프롬프트에 "참조 k번의 어떤 요소를 유지하고 무엇을 교체하는지"를 명시한다.
   ③ 산출 후 frame_index에 {path, characters, space, shot}을 등재한다.
4. **비용·생성** → 검증: 유료면 `[[cost-preview-confirm]]`. 유료 호출 직전 체크포인트:
   `check_manifest.py check --manifest media/manifest.jsonl --output <경로> --hash <inputs_hash>`
   — exit 0(RESULT=skipped)이면 호출을 생략하고 기존 산출물을 쓴다. 큐 제출 → 폴링 →
   결과 URL GET → `media/images/`에 저장. 응답 `images[].url`. 결과를 `record`로 append.
4.5 **방향 가드** → 검증: 산출 이미지의 실측 가로/세로가 요청 aspect와 불일치하면(세로
   요청에 가로 산출, 역도 동일) 즉시 실패로 처리하고 프롬프트에 방향 지시를 강화해 1회
   재생성한다 — 잘못된 방향이 하류 유료 단계(영상화·업스케일·합성)에 도달하지 않게.
4.7 **[서사 모드] Best-of-2 심사 게이트(조건부)** → 검증: 서사 모드이고 해당 프레임이
   (새 공간 첫 프레임 ∨ 구도 급변 ∨ 다인물 상호작용)일 때만 — 동일 프롬프트·다른 seed로
   2장 생성 후 심사 VLM(생성 모델과 다른 모델 — producer≠evaluator)이 3축 rubric(캐릭터
   일관성 > 공간 일관성 > 서술 정확도 우선순위, 전 동률이면 후보1 채택 — 결정론)으로 1장
   선택. 둘 다 캐릭터 축 불합격이면 재생성 1회, 그래도 불합격이면 NO_GO 상위 보고(무한
   루프 금지). 탈락본은 `media/images/rejected/`에 보존(삭제 금지), 심사 사유를 manifest에
   append. N=2 고정(3장 이상 금지 — 선택 노이즈). 상세 설계=`_work/vimax-w0/b4_bestof2/BESTOF2_GATE_DESIGN.md`.
5. **자기교정** → 검증: 거부·실패(세이프티·파라미터 오류)면 사유를 읽고 프롬프트/파라미터를
   교정해 1~2회 재시도.

## 출력 계약

`media/images/NN.<ext>` + 매니페스트 항목(모델경로·재작성 프롬프트·seed·aspect·resolution·실비용).
상위 `[[media-gen]]`로 반환. 편집·참조가 필요하면 `[[media-gen-edit]]`, 영상화는 `[[media-gen-video]]`.
