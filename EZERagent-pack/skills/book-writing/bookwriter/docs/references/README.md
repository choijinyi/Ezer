# References

외부 도구/시스템 LLM-친화 문서를 모은다. 모델이 컨텍스트에 가져갈 수 있는 작은 스니펫만.

## 형식

`<topic>-llms.txt` 파일로 보관. 한 파일 ≤ 50KB. 더 크면 분할.

## 우선순위 슬롯
- `design-system-reference-llms.txt` — shadcn/Tailwind 패턴 (TBD)
- `nixpacks-llms.txt` — 컨테이너 빌드 (TBD)
- `uv-llms.txt` — Python 도구 체인 (필요 시)
- `typst-llms.txt` — 조판 엔진 (TBD)
- `pandoc-llms.txt` — EPUB 변환 (TBD)

## 갱신 정책

- 분기마다 검토. 오래된 API는 갱신 또는 제거.
- LLM이 잘못된 정보를 자주 쓰는 영역만 추가한다 (모델이 잘 아는 영역은 노이즈).
