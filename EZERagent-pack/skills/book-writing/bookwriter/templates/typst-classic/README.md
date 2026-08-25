# typst-classic

A5 단행본 템플릿. 에세이, 짧은 책, 논문 모음에 적합.

## 기본값
- 본문: Source Serif 4 / Noto Serif KR fallback, 11pt
- 페이지: A5 (148×210mm), 좌우 18mm 상하 24mm
- 첫 줄 들여쓰기 1.2em, 줄간격 0.95em

## 빌드
```
typst compile --root build/<job> build/<job>/book.typ build/<job>/preview.pdf
```

## 변수
typesetter agent가 채우는 placeholder:
- `{{title}}` — 책 제목
- `{{author}}` — 저자 (콤마 구분)
- `{{lang}}` — `ko` / `en` / ...
- `{{cover_path}}` — 표지 파일 상대경로 (없으면 빈 문자열 → 표지 생략)
- `{{body}}` — 본문 (Markdown → Typst 변환 결과)

## 커스터마이징
이 템플릿을 직접 수정하지 말 것. 복사해서 `templates/typst-myname/`을 만들어라. 사용자별 변형은 별도 템플릿이다.
