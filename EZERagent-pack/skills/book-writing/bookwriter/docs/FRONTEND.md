# FRONTEND.md

> **상태: Track 2 (보류).** 현재 1차 타겟은 로컬 집필 도구. 본 문서는 향후 웹 서비스화 시 참조용이며, M3 이전에는 작업 대상 아님.

## 스택

- Next.js 16 App Router (Cache Components)
- React 19 + Server Components 기본
- Tailwind CSS v4
- shadcn/ui (registry 커스텀 가능)
- AI SDK v6 (Vercel AI Gateway 경유)

## 폴더 규칙

```
app/
├── (marketing)/         # 랜딩, 가격, about
├── (app)/               # 인증된 사용자 영역
│   └── jobs/[id]/
├── api/                 # Route Handlers
└── layout.tsx
components/
├── ui/                  # shadcn 원시
├── book/                # 도메인 (TocTree, PageThumb, DecisionGate)
└── upload/
lib/
├── pipeline/            # 에이전트 호출 wrapper
├── storage/             # Blob/FS 추상
└── schemas.ts           # zod
```

## 데이터 패칭 규칙

- 기본은 Server Component + `use cache` directive
- 사용자별 데이터는 `cacheTag(userId)` 후 `updateTag`로 무효화
- Client Component는 폼/실시간 진행률에만 사용
- `fetch`는 절대 직접 호출하지 않는다 — 항상 lib 레이어 경유

## 진행률 표시

파이프라인 단계는 SSE 스트림으로 푸시. AI SDK의 `streamText` 패턴 차용. 사용자는 어떤 에이전트가 도는지 보고 싶어한다.

## 접근성

- 모든 인터랙션은 키보드만으로 완료 가능
- PDF 미리보기는 텍스트 레이어 보존 (스크린 리더 지원)
- 결정 카드는 `role="dialog"` + 포커스 트랩

## 성능 예산

- LCP < 2.5s on 4G
- 번들: 메인 라우트 < 150KB gzipped
- 이미지: `next/image` + Vercel 자동 최적화
- 폰트: `next/font` self-host
