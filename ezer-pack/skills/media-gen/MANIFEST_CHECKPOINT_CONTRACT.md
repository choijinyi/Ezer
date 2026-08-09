# MANIFEST_CHECKPOINT_CONTRACT v1 — 영상 워크플로우 체크포인트·비용 원장 계약 (B2)

> 근거: ViMax 연구 OPP-22(파일시스템=체크포인트 권위 `exists→load`의 강화판) · 접합: media-gen 스킬군이 이미 기록하는 매니페스트 항목(모델경로·프롬프트·seed·실비용)의 형식·위치 통일.
> 유기성: 기록 = media-gen 하위 5스킬 · 소비 = 재실행 시 자기 자신 + youtube-video-pipeline(비용 보고) + video-verify(산출물 대장 대조) — U2 충족.

## 파일: 프로젝트 루트 `media/manifest.jsonl` (append-only)

레코드 스키마(1줄 1레코드):
```json
{"ts": "2026-07-04T15:00:00+09:00",
 "skill": "media-gen-image",
 "output": "media/images/03.png",
 "inputs_hash": "<sha256 — 아래 해시 규약>",
 "model": "fal-ai/nano-banana-pro",
 "params": {"aspect_ratio": "16:9", "seed": 42},
 "cost_usd": 0.13,
 "status": "ok" }
```
- `status` ∈ {ok, failed, rejected}(TOOL_RESULT_VOCAB 부분집합). 체크포인트 판정에는 **ok만** 유효.
- append-only — 수정·삭제 금지(감사·retention). 손상 줄은 무시하고 계속(관대 파싱).

## 해시 규약 (재생성 필요성의 결정론 판정)

`inputs_hash = sha256( "\n".join([최종 프롬프트(재작성 후), 정렬된 참조이미지 경로들, 모델 경로, 정렬된 핵심 파라미터 k=v]) )`
- 프롬프트·참조·모델·파라미터 중 하나라도 바뀌면 해시가 바뀌어 재생성 발동 — "경로만 있으면 스킵"(ViMax 원형)의 함정(프롬프트 수정이 무시됨)을 막는 강화.

## 체크포인트 규약 (전 media-gen 하위 스킬 공통 — B3 diff로 삽입)

유료 호출 **직전**:
1. `python3 check_manifest.py check --manifest media/manifest.jsonl --output <경로> --hash <inputs_hash>`
2. exit 0(= output 실존 ∧ 동일 해시 ok 레코드 존재) → **RESULT=skipped** — 호출 생략, 기존 산출물 사용.
3. exit 1 → 생성 진행 → 성공/실패를 `record` 서브커맨드로 append.

## 비용 원장 규약

- `python3 check_manifest.py total-cost --manifest media/manifest.jsonl` → 프로젝트 실지출 합산(결정론).
- youtube-video-pipeline은 단계 전환 보고와 종료 보고에 이 값을 병기(기존 "세션 총비용 포함" 규칙의 결정론 구현).
- cost-preview-confirm(사전 추산)과 상보: 사전=추산 게이트, 본 계약=사후 실측 원장 + 재실행 절약.
