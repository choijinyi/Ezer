# cbs-core-competency-manual

CBS M&C **핵심역량교육**(「AI 기반 뉴스 콘텐츠 제작·기사 생성 자동화 실무」, 80시간·7회) 교육 매뉴얼북. 전사교육 매뉴얼(`cbs-ai-training-manual`)의 후속 권으로, **이론 + 실습 코드** 중심이다.

## 구성

```
manuscripts/cbs-core-competency-manual/
├── book.json              # 7장 본문 + 머리말 + 참고자료
├── 00-preface.md          # 머리말
├── 01-chapter.md ~ 07-chapter.md   # 7개 회차(본문)
└── 99-references.md       # 부록·참고자료
```

## 편집 규칙

- **각 파일의 첫 `#` 줄이 그 장의 제목**이 된다. `book.json.chapters[i].title`은 fallback이다.
- 순서를 바꾸려면 파일 이름이 아니라 `book.json.chapters` 배열을 재배열한다(파일명 prefix `NN-`은 정렬 fallback일 뿐).
- 본문은 특정 조판 템플릿에 묶이지 않는 **표준 Markdown**으로 작성한다. 조판은 사용자 템플릿에서 별도로 진행한다.

## 집필 표준

- 각 회차는 1권과 동일한 구조를 따른다: 회차정보표 → 학습 목표 → 핵심 개념 → 실습 → 체크리스트 → 핵심 요약 → 다음 회차 예고 → 핵심 용어.
- 본문 표시: `[개념]` `[실습]` `[팁]` `[주의]`. 이모지는 쓰지 않는다.
- 다이어그램은 표 또는 코드블록 ASCII로 대체한다(이 머신에 mermaid 미설치).
- 실습 코드는 파이썬을 기본으로 하며, API 키·외부 데이터 처리 시 보안 원칙을 본문에 명시한다.
