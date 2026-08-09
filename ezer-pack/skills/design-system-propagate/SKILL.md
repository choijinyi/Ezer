---
name: design-system-propagate
description: 확정된 디자인 원형(master.html 최상위 원형 + 토큰 실파일)을 N개 페이지에 일관 전파하는 빌드 하네스: 컴포넌트 인벤토리 추출→공유 CSS 분리→페이지맵→토큰/컴포넌트 링크→한 페이지씩 조립·헤드리스 렌더 검증→일관성 게이트(토큰만·하드코딩hex 0·radius0·다크기본·대비계산·주석*/점검·양테마). design-token-system(토큰층)+vibe-design(원칙) 위에 구성. ezer-homepage R3 7페이지 전파에 재사용.
---

# design-system-propagate

> 출처: ezer-homepage RSI(R2→R3, 2026-06-15). vibe-design 워크플로우(레퍼런스→스타일가이드→master.html→Rule→test→본제작)의
> "master.html 최상위 원형 → 본제작(페이지 전파)" 단계를 결정론 하네스로 구체화·발전.
> 토큰층=[[design-token-system]] · 원칙=vibe-design · 함정=[[css-comment-star-slash-kills-root-tokens]] · 방법론=[[design-system-evidence-based-methodology]].

## 언제 쓰나
- 확정·검증된 디자인 원형(예: master.html 최상위 원형 + tokens.*.css)을 **여러 페이지에 전파**할 때(ezer-homepage R3: index + about/books/insights/media/speaking [+신규 AI-Lab]).
- 디자인 일관성을 유지하며 사이트 전체에 한 디자인 시스템을 적용할 때.

## 순서
1. **원형 고정(SOT 잠금)**: master.html(최상위 원형)+tokens 실파일을 진실로 고정. `design-token-system` 스킬로 토큰 검증 통과부터.
2. **컴포넌트 인벤토리 추출**: 원형서 반복 컴포넌트를 목록화(header/nav·hero(+초상슬롯)·badge 3종(draft/proof/real)·banner card(bg有/無)·button(CTA+서브)·노출 그리드·foresight 모티프·data-table ledger·card grid·footer) → 프로토타입 인라인 CSS를 **공유 components.atlas.css**로 분리(중복 제거).
3. **페이지 맵 작성**: 각 페이지의 콘텐츠 구조를 컴포넌트로 매핑(어느 페이지가 어느 컴포넌트를 쓰는지 표). 실제 페이지 roster를 grep으로 확인(추측 금지·환각0).
4. **링크 표준화 + @layer(R3 검증·헤드라인)**: 모든 페이지가 `tokens.atlas.css`+`components.atlas.css` 링크(★root-relative `/css/...`=서브페이지 ../ 버그 제거). 첫 로드 파일이 레이어 순서 선언 `@layer reset, tokens, base, components, pages, utilities;` → tokens=@layer tokens·components=@layer components·page-*.css=★`@layer pages`(컴포넌트를 특이도 전쟁 없이 결정론 오버라이드). ★unlayered 규칙은 전 레이어를 이기므로 page CSS도 반드시 @layer에 넣을 것. 클래스=BEM(특이도 (0,1,0) 고정). 근거=MDN @layer(Baseline 2022·93.7%)·Smashing 2025·ITCSS 순서. ★@layer는 충돌 없으면 픽셀 무변경(검증=래핑 전후 렌더 byte-identical)이라 안전.
5. **전파 실행(한 번에 한 페이지)**: 페이지마다 컴포넌트 조립 → 헤드리스 렌더 검증 → 통과 후 다음. ★구조·treatment만(실콘텐츠=content lane 워커153 불가침).
6. **일관성 게이트(페이지마다)**: 아래 '확인하는 방법' 전수.
7. **content 협업·게이트 통과 보고**: 페이지별 완료 push, 전 페이지 통과 시 라운드 종결.

## 주의할 점 (함정 — 겪을 때마다 한 줄씩 누적하라)
- ★content lane 침범 금지: design은 구조·컴포넌트·treatment만. 실문구/수치는 워커153. placeholder는 draft 배지로 표기(real 오인0).
- 하드코딩 hex/px 금지: 색·간격은 토큰만. 페이지마다 새 리터럴 생기면 드리프트.
- 페이지 고유 CSS 비대화 금지: 공유 컴포넌트로 못 빼면 컴포넌트를 일반화(페이지별 복붙 금지).
- ★CSS 주석 본문 `*/` 트랩(주석 조기종료→토큰 전멸·흰배경) — 매 파일 균형 점검.
- eval v7 LOCKED 무접촉(작업존=draft 또는 명시 라이브 파일만). 폰트 변경은 renderedFontFace 게이트 hard FAIL 위험([[eval-renderedfontface-gate-trap]]) — 라이브 반영 전 master 확인.
- 서버 최소: 헤드리스 file:// 렌더(무서버). file:// 하위 CSS는 인라인 or --allow-file-access-from-files.
- 한 번에 한 페이지(일괄 전파 후 한꺼번에 검증 금지 — 회귀 추적 불가).
- ★@layer 캐스케이드 전파(R3 RSI·WebSearch 검증 2026 best practice): `@layer tokens, components, page;` 순서로 래핑하면 page 오버라이드가 components>tokens를 import 순서·specificity 무관하게 결정론적으로 이김(빌드리스·96%+ 지원). 페이지 고유 CSS가 커질 때 specificity 전쟁 방지. design 원형이 deferred했으면 RSI로 타당성 입증 후 라이브 flip 시 적용.
- ★폰트 게이트 라이브 flip 블로커(정정): eval renderedFontFace/glyphCoverage HARD gate는 **현 LIVE 디자인의 폰트를 핀**한다(LUMEN=Pretendard+Space Grotesk). 새 방향이 그 폰트를 버리면(예: ATLAS가 Space Grotesk 제거) 라이브 flip 시 2 gate 동시 hard FAIL=composite 0. draft는 무관(eval 비실행). 라이브 flip=master의 eval 재핀 결정(producer≠evaluator·워커 eval 편집 금지). [[eval-renderedfontface-gate-trap]].
- ★페이지당 1 sub-agent 병렬 전파 가능(컨텍스트 절약): 각 에이전트에 (소스 페이지=verbatim·완성 플래그십=정본 패턴·components/tokens CSS) 제공·콘텐츠 verbatim만(재생성 금지=환각0). 단 **master/워커가 전 페이지 독립 재검증**(렌더 Read+게이트+verbatim 대조)=producer≠evaluator·자가보고 미신뢰.

## 확인하는 방법 (검증 — 겪을 때마다 한 줄씩 누적하라)
- 페이지마다 Chrome `--headless=new` 무서버 렌더 → Read로 육안 확인(다크+라이트 양 테마).
- 하드코딩 색 0: `grep -nE '#[0-9A-Fa-f]{3,6}' <page>.css | grep -v tokens` = 비어야 함(컴포넌트/페이지 CSS엔 리터럴 금지).
- 주석 균형: `grep -o '/\*' f.css|wc -l` == `grep -o '\*/' f.css|wc -l` (전 CSS 파일).
- 대비 계산(design-token-system 스니펫)으로 페이지 신규 색쌍 검증(<4.5 본문·<3 대형 수정).
- 컴포넌트 일관성: 같은 컴포넌트가 페이지마다 동일 클래스·구조인지(시각 diff).
- radius 0·모노 라벨·다크 기본·노출 그리드가 전 페이지 유지.
- ★콘텐츠 verbatim 무손실 독립 교차검증(환각0): 소스 distinctive 문자열이 draft에 존재(`grep -qF`)·카탈로그 완전성 카운트 소스==출력(R3 실측: books 제목 34=34·가시 shop링크 6=6·media youtube 122=122). exact-quote grep 주의(`class="book"`는 `class="book reveal in"` 불일치 — 부분일치/제목 추출로 카운트).
- ★헤드리스 양테마 1콜: 다크=원본 렌더·라이트=`sed 's/data-theme="dark"/data-theme="light"/'` 사본 렌더. 페이지 실높이는 PIL로 bg 동일행 역스캔해 측정(긴 페이지 잘림 방지). 산출 PNG는 render/ 통합·임시 _*_light_src.html 삭제.
- ★a11y probe는 전 페이지 루프로(단일페이지 only면 페이지별 위반 누락): playwright+axe-core로 page 변수 돌려 axe violations·skip-link focus left·mobile nav visible/total·docScrollW>viewport(overflow) 전수. 리뷰어 a11y 불일치는 설득 아니라 같은 probe FRESH 재실행(producer≠evaluator·stale 스냅샷 판별).
- ★link-in-text-block 트랩(WCAG1.4.1 serious): 텍스트블록 내 인라인 링크가 색만으로 구분(accent vs muted <3:1)+밑줄無 → axe serious. 인라인 링크엔 text-decoration:underline 필수. 단 블록 CTA(.book-link)·셀단독 링크(.ledger a)는 텍스트블록 인라인 아니라 미플래그=미변경(불필요 밑줄 회피).
- ★skip-link 함정: `.skip-link{left:-9999px}`는 @layer pages라도 utilities가 left를 미override하면 focus에도 은닉(2.4.1 FAIL) → 페이지 인라인서 .skip-link/.sr-only 제거하고 interactions(@layer utilities)의 focus-reveal 정본에 위임.
- (라이브 반영 시) eval LOCKED 채점기 무회귀 — master 잠금채점.
- ★렌더 perf 측정 하네스(R4 RSI·장문 페이지): Playwright CDP `Performance.getMetrics`로 LayoutDuration 측정(×1000=ms·N회 median). ★content-visibility 같은 '오프스크린 렌더 스킵' 기법은 ★강제 풀레이아웃(`document.body.offsetHeight`) 금지=이득 상쇄 → goto(waitUntil networkidle) 후 메트릭만(자연 초기렌더). content-visibility:auto+contain-intrinsic-size:auto <fallback>를 `.sec`에 적용→장문 초기 layout 큰폭 감소(R4 실측 index 32%·오프스크린량 비례)·★회귀검증 필수(axe 0 유지[a11y트리 보존]·풀렌더 height=baseline 동일[시각 무손상]·CLS=intrinsic-size 공간예약). progressive(미지원 정상폴백). [[frontend-perf-content-visibility]].
- ★MPA 즉시네비(Speculation Rules): 정적 멀티페이지는 `<script type="speculationrules">{"prefetch":[{"source":"document","where":{"href_matches":"/*"},"eagerness":"moderate"}]}</script>`(body끝)로 hover prefetch. ★file://서 측정 불가(http 필요)=draft 수치 주장 금지(환각0)·라이브 측정. Chromium 전용(graceful). axe-on-file://의 CSS XHR CORS 콘솔에러는 하네스 아티팩트(page 결함 아님).
- ★★실 CWV(FCP/LCP)·render-blocking 판정은 ★반드시 throttle에서(R7 RSI): http 서버(`ezer run -- python3 -m http.server <port>`·측정직후 force-kill·고아0) + Playwright `ctx.newCDPSession(page)`→`Network.emulateNetworkConditions`(Slow4G: download 180000 B/s·latency 562.5ms)·cacheDisabled·FCP=`getEntriesByName('first-contentful-paint')`·N median. ★localhost(RTT≈0)는 외부 CSS 왕복비용을 0으로 ★은닉=render-blocking headroom 오판("작음") 유발 — R7 실증(localhost FCP 96ms→Slow4G 1652ms). ★render-blocking 페널티=RTT 지배(바이트 아님): minify 51%↓도 FCP −124ms뿐·왕복제거(inline/critical CSS)는 −688ms=강한 레버. 라이브 권고=critical inline+async full(FCP↑+캐싱보존). [[frontend-perf-content-visibility]].
- ★critical CSS 패턴 검증(R8 RSI): inline-min(concat→minify→head 인라인·외부link 제거)=render-blocking 제거 라이브 권고(Slow4G FCP −832ms/−50.9% 실측·axe+computed-style byte-identical 무회귀·FOUC0). ★critical+async 분할 전 CSS 얽힘 감사 필수: a11y(skip-link/focus/forced-colors)+반응형+모션이 한 파일이면 분할 시 async 윈도우 FOUC 위험>이득→소규모(≲50KB)는 inline-all이 안전. ★axe 검증은 룰셋 명시: 기본 룰셋=best-practice(heading-order 등) 포함이라 "axe 0"는 ★WCAG 한정(`runOnly:["wcag2a","wcag2aa"]`)인지 best-practice 포함인지 구분해 보고(혼동 방지).
- ★CWV 결론은 프로덕션 프로토콜(HTTP/2)서 적대적 재검증(R9 RSI): localhost 측정은 HTTP/1.1(python http.server)이나 정적호스트(GitHub Pages·Netlify)는 HTTP/2 → 하네스 `_h2server.mjs`(Node http2 TLS·self-signed·ALPN h2·`nextHopProtocol` 확인)로 재측정. ★render-blocking=RTT-gated=프로토콜 무관(H2 다중화는 소수 파일엔 무이점·H1.1도 병렬 6커넥션)→inline 이득 H1.1≈H2(−824 vs −832ms). 결론을 프로덕션 조건서 검증해야 권고가 robust.
