# 공개 사용 안내 페이지 (ezer-guide)

`index.html` 이 공개 가이드 페이지의 **단일 소스**다. 외부 의존 없는 단일 HTML
파일(인라인 CSS + 인라인 스크립트 한 덩이)이라 그대로 열어도 완전히 동작한다.

- 공개 주소: https://ezer-guide.vercel.app/
- 호스팅: Vercel 프로젝트 `ezer-guide` (team `choijinyis-projects`)

## ⚠ 저장소 푸시로는 배포되지 않는다

Vercel 프로젝트가 **이 저장소에 git 연결돼 있지 않다.** 따라서 여기에 커밋·푸시해도
공개 페이지는 바뀌지 않는다 — 배포는 별도 단계다. 이 파일을 두는 목적은 배포 자동화가
아니라 **원본을 버전 관리 아래 두는 것**이다(종전에는 사본이 Vercel 에만 있어, 고치려면
라이브 페이지를 되받아 와야 했다).

배포는 둘 중 하나로 한다.

1. **Vercel CLI** (사람이 손으로 할 때)
   ```bash
   npx vercel link --project ezer-guide      # 처음 한 번
   npx vercel deploy --prod docs/guide
   ```
   ※ 이 경로는 문서상의 동등 절차이며 이 저장소에서 실측하지 않았다.
   실제 배포는 아래 2번(Vercel API)으로 수행했다.

2. **Vercel API** (에이전트 세션에서 수행한 방식)
   `POST /v13/deployments` 에 `project=ezer-guide`, `target=production`,
   `files=[{file:"index.html", encoding:"utf-8", data:<본문>}]` 로 인라인 전송.

배포 뒤에는 **라이브 페이지를 되받아 이 파일과 전문 대조**하라 — 인라인 전송은 전사
오류가 끼기 쉬운 경로다(과거 1건 발생·수정).

```bash
curl -sL -o /tmp/live.html https://ezer-guide.vercel.app/ && diff docs/guide/index.html /tmp/live.html
```

## 버전 표기는 손으로 고치지 않아도 된다

페이지 하단 스크립트가 GitHub API(`releases/latest`)에서 최신 릴리스를 읽어 버전 라벨·
내려받기 링크·파일 크기를 **브라우저에서 자동으로 채운다.** 새 버전을 낼 때마다 이
파일을 고칠 필요가 없다.

HTML 에 박혀 있는 `v0.13.17` 과 `FALLBACK` 값은 **스크립트가 실패했을 때(오프라인·
API 차단·자바스크립트 끔) 남는 폴백**이다. 틀려도 치명적이지 않지만, 가이드 내용을
손볼 일이 생기면 그때 같이 맞춰 두는 편이 낫다.

## 릴리스 레인에 영향이 없다

`scripts/auto-release.sh` 의 레인 판정이 `docs/` 를 "앱에 실리지 않는 경로"로 분류한다
(`lane=none`). 이 디렉터리만 고쳐 main 에 올려도 새 버전이 서지 않는다.
