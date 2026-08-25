# manuscript-default

bookwriter의 원고 스캐폴드 자료. 본문 장 파일과 `book.json`은 `/new` 명령이 동적으로 생성하며, 이 디렉토리에는 **그대로 복사되는 파일들만** 둔다 (`README.md`, `00-preface.md`, `99-references.md`).

## 사용

```
/new --scaffold mybook                  # 기본: 14장 본문
/new --scaffold mybook --chapters 7     # 7장
/new --scaffold mybook --chapters 20 --lang en
```

## 생성 결과 (예: --chapters 14)

```
manuscripts/mybook/
├── book.json              # /new가 N에 맞춰 생성
├── 00-preface.md          # 머리말 (이 디렉토리에서 그대로 복사)
├── 01-chapter.md          # /new가 N개 동적 생성 (NN-chapter.md)
├── 02-chapter.md
├── ...
├── 14-chapter.md
└── 99-references.md       # 참고문헌 (그대로 복사)
```

## 편집 규칙

- **각 파일의 첫 `#` 줄이 그 장의 제목**이 된다. `book.json.chapters[i].title`은 fallback이다.
- 장이 더 필요하면: 새 파일(예: `15-chapter.md`)을 만들고 `book.json.chapters` 배열에 추가한다.
- 장이 덜 필요하면: 파일 삭제 + `book.json`에서 줄 제거.
- 순서를 바꾸려면 **파일 이름이 아니라 `book.json.chapters` 배열**을 재배열한다 (파일명 prefix `NN-`은 정렬 fallback일 뿐).

## 표지 (선택)

표지는 자동 생성된다. 직접 만든 표지를 쓰려면 `manuscripts/<name>/`에 다음 중 하나를 둔다:
```
cover.svg     # 우선순위 1
cover.png     # 우선순위 2
cover.jpg     # 우선순위 3
cover.jpeg    # 우선순위 4
cover.webp    # 우선순위 5
```
첫 번째로 발견되는 파일이 사용되고 자동 생성은 비활성화된다. 나중에 마음이 바뀌면 그 파일을 지우고 새 job을 돌리면 자동 생성으로 돌아간다.

## 다음 단계

각 장을 채운 뒤:
```
/new manuscripts/mybook
```
파이프라인이 시작된다.
