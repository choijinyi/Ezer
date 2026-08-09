---
name: media-gen-edit
description: 참조 이미지를 보존·편집하는 하위 스킬 — 입력 이미지를 URL로 전달해 정체성(얼굴 등)을 유지한 채 편집/합성한다(nano-banana-pro/edit, image_urls 배열). media-gen 편집 관문. "이미지 편집 / 참조 이미지 / 정체성 보존 / image edit / reference" 맥락에서 발동.
---

# media-gen-edit

레퍼런스 이미지를 주고 편집한다. 핵심은 **정체성 보존** — 얼굴/대상을 망가뜨리지 않고
편집한다(원본 영상의 "참조 이미지를 다른 사람으로 만들지 않는" 처리).

## 절차

1. **입력 업로드** → 검증: 로컬 참조 이미지를 fal에 업로드해 URL 확보(`fal_client.upload_file`).
   여러 장이면 전부 URL 배열로.
2. **편집 지시** → 검증: `prompt`에 *무엇을 바꾸고 무엇을 유지할지* 명시(정체성·포즈·배경 등).
   거친 의도는 `[[media-gen-image]]`처럼 재작성.
3. **모델·호출** → 검증: `fal-ai/nano-banana-pro/edit`. 입력은 **`image_urls`(URL 배열)** +
   `prompt`. 라이브 스키마 조회 후 호출(최대 다수 참조·다인 정체성 일관 지원). 스키마 하드코딩 금지.
4. **비용·자기교정** → 검증: 유료면 `[[cost-preview-confirm]]`. 입력 용량/포맷 제약(모델별)
   초과면 압축·변환 후 재시도.
5. **정체성 점검** → 검증: 결과가 참조 대상의 정체성을 유지하는지 확인(왜곡 시 프롬프트 보강·재시도).

## 출력 계약

`media/images/edit-NN.<ext>` + 매니페스트(모델경로·참조 URL·프롬프트·seed·실비용). 상위
`[[media-gen]]`로 반환. 영상화는 `[[media-gen-video]]`.
