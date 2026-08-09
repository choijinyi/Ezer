---
name: media-gen-upscale
description: 영상·이미지를 고해상도로 업스케일하는 하위 스킬 — fal.ai Topaz 모델로 저해상 클립을 선명하게(배율 기반). 생성 B-roll뿐 아니라 임의 저화질 소스에도 적용. media-gen 업스케일 관문. "업스케일 / 화질 향상 / 해상도 올리기 / topaz upscale" 맥락에서 발동.
---

# media-gen-upscale

저해상 클립을 선명하게 올린다(원본 영상의 Topaz 업스케일 — 연 $400 구독을 건당 수십 센트로).
생성 B-roll만이 아니라 **아무 저화질 영상**(다운로드 소스 등)에도 쓴다.

## 절차

1. **입력 준비** → 검증: 대상 영상/이미지를 URL로(`video_url`). 로컬이면 업로드 후 URL.
2. **모델·배율** → 검증: 영상=`fal-ai/topaz/upscale/video`, 이미지=`fal-ai/topaz/upscale/image`.
   **`upscale_factor`는 목표 해상도가 아니라 배율**(예: 2.0=가로세로 2배). 라이브 스키마 조회 —
   `model`(Proteus 등)·`target_fps`(보간) 등 옵션은 모델별. 스키마 하드코딩 금지.
3. **비용** → 검증: 유료 종량제 → `[[cost-preview-confirm]]`.
4. **생성** → 검증: 큐 제출 → 폴링 → 결과 URL → 저장. 입력 대비 화질 향상을 샘플 프레임으로 확인.

## 출력 계약

업스케일된 파일(`media/broll/NN-up.mp4` 등) + 매니페스트(모델경로·배율·실비용). 상위
`[[media-gen]]`로 반환. 본 영상 최종 해상도 정합에 사용.
