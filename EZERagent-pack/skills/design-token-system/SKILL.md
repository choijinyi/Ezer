---
name: design-token-system
description: 구조적 디자인 시스템 토큰·그리드·다크모드를 근거기반으로 구축: 2-tier(primitive→semantic) DTCG 토큰·테마=alias 재지정·APCA/WCAG2 대비 실측·타입단위 파생 Swiss 그리드+모듈러 스케일·데이터를 정체성으로(generative)·헤드리스 렌더 실측(+CSS주석 */ 트랩 점검). design 워커가 디자인 시스템/토큰/다크모드를 만들 때 발동.
---

# design-token-system

> 출처: EZERagent-homepage RSI 학습루프(R2, 2026-06-15) — DTCG 2025.10·Nathan Curtis(eightshapes)·Atlassian·
> Gerstner/Müller-Brockmann·Tim Brown(ALA)·Utopia/Andy Bell·Tufte·Giorgia Lupi·APCA(Myndex)·Material/Apple HIG.
> 모든 근거는 WebFetch 검증·대비는 자체 계산. 자기채점 금지 — spec/계산/출처로 입증.

## 언제 쓰나
- 디자인 토큰 파일(CSS 커스텀 프로퍼티)·디자인 시스템·다크모드 테마를 새로 만들거나 리팩터할 때.
- "구조적/모더니즘/Swiss/데이터=정체성" 방향의 사이트를 구축할 때.
- 기존 flat `:root` 토큰을 손보거나, 색 대비(특히 다크모드)를 검증할 때.

## 순서
1. **2-tier 토큰**: TIER1 PRIMITIVES(리터럴은 여기만 `--p-*`)→TIER2 SEMANTICS(canonical 이름 `--bg/--ink/--accent…`은 `var(--p-*)` 참조만). 리터럴 중복 금지. (근거 Curtis Options/Decisions·W3C DTCG alias·Penpot one-directional). 단일 사이트는 component 티어·Style Dictionary·JSON 빌드 생략(과설계).
2. **테마=alias 재지정**: `[data-theme]`는 semantics만 re-point(raw 재선언 금지). 대비용 신규 색은 primitive로 추가 후 re-point. (Atlassian value-mapping).
3. **대비 실측(환각0)**: 눈대중 금지. WCAG2 ratio를 sRGB relative-luminance로 계산(아래 스니펫) + APCA Lc 가이드. 본문≥4.5:1(APCA Lc75)·대형/UI≥3:1(Lc60). ★다크모드는 WCAG2가 과대평가→APCA 우선(Myndex). 고채도 액센트(버밀리언·네온)=대형/볼드 전용, 소형 body 금지.
4. **다크 베이스**: 순흑(#000~#0E0E0E) 회피→#121212+(Material). elevation=섀도우 아닌 lighter surface 단계. 대면적 채도 낮춤. 텍스트=오프화이트(순백 아님). ★theme-aware elevation(R8): 다크=lighter surface(luminance·섀도우 무효)·라이트=섀도우(표준)이나 ★white-ceiling(surface=흰색=더 밝게 불가)→플로팅/오버레이는 보더 또는 하드 섀도우로 깊이. 비대칭은 정상(다크=1급 컨텍스트). 섀도우 단독 금지=보더 병행. flat/no-shadow 정체성이면 ★하드 구조 섀도우(sharp·offset·brutalist)는 기능 분리用 허용≠소프트 글로우 데코. 카드는 1px 하드룰 보더가 양테마 처리.
5. **타입 단위서 그리드 파생**(Swiss): 그리드를 장식 라인으로 그리지 말고 타입 단위(=body line-height=baseline)서 파생. 컬럼 수는 measure를 나머지 없이 나누게(Gerstner). 모듈러 스케일=단일 비율(major third 1.25/perfect fourth 1.333…) base서 생성, `clamp(min, rem+vw, max)`로 fluid(Utopia/Bell). 여백·line-height=baseline 배수. `text-box:trim-both`로 baseline 정합(지원 가드).
6. **데이터=정체성(generative)**: 도메인 실제 다이어그램/데이터를 브랜드 언어로(장식 아님). 규칙(programme)을 설계→마크는 출력(Gerstner/MIT Media Lab/Whitney responsive). data-ink 최대화(Tufte), "data as institutional lens"(Lupi). 정적 SVG보다 실데이터 바인딩 generative 마크.
7. **헤드리스 렌더 실측**: 무서버 file://로 Chrome `--headless=new` 스크린샷→Read로 육안 확인. file:// 하위 CSS는 `<style>` 인라인하거나 `--allow-file-access-from-files`. ★렌더 생명주기=surgical(PID capture+그 PID/--headless/unique-profile만 kill·broad pkill 절대금지·[[headless-chrome-render-lifecycle-and-kill-safety]]). 애니 end-state는 `--virtual-time-budget=N`으로 시간 advance 후 캡처.
8. **모션 시스템(R4 추가)**: 모션도 토큰화 = semantic easing set(standard/out=decelerate/in=accelerate/emphasized=signature/instrument=기계적)+duration scale(instant~signature)+stagger. 근거=Material 3 motion·Val Head meaningful motion. ★single signature motion(restraint=1개 표현적 모션+나머지 절제)·meaningful>decorative(모션이 구조/관계/인과를 가르쳐야)·reduced-motion first-class(`@media(prefers-reduced-motion:no-preference)` 게이트·끄면 정적 등가·non-vestibular). 데이터/다이어그램은 kinetic build(staged·transform/opacity compositor-only)로 구조를 가르치되 default=정적 full. scroll-driven(`animation-timeline:view()` ~85%·PE)·cross-doc View Transitions(`@view-transition` 라이브·★file:// 불가)=progressive enhancement+정적 fallback. 회피=scroll-jack·everything-bounce·AI-gimmick.
9. **타이포·폰트 로딩(R5 추가)**: 폰트도 토큰화 = primitive 스택은 **실제 로드되는 폰트만 1순위**(상용·미라이선스 폰트 1순위 = 배포 시 시스템 폴백 = 잠복 결함). 무료 가변 grotesk 후보=Space Grotesk(시그니처/미래)·Schibsted(UI중립)·Hanken(본문)=전부 OFL·variable·self-host. **로딩=self-host(캐시 파티셔닝 후 CDN 이점 소멸·Web Almanac)+variable woff2(가변=woff2만)+서브셋(unicode-range)+비차단(`media=print→onload`+noscript)**. ★`font-display`: 폰트게이트/실렌더 보장이 필요하면 `swap`(로드 시 반드시 렌더=결정론)·`optional`은 폴백-방문내내 가능(미렌더 위험). swap-CLS는 **폴백 @font-face 메트릭 오버라이드**(`size-adjust`/`ascent-override`/`descent-override`/`line-gap-override`)로 제거 — 값은 **fontaine/Capsize로 생성**(추정 금지=환각). CJK 본문=dynamic-subset CDN이 1P self-host보다 req/bytes 우위(실측 검증). data:URI 인라인 서브셋=tpOrigins↓이나 preload 불가·시트 비대(트레이드오프 측정). 근거=web.dev font best practices·DebugBear·corewebvitals.io.
10. **데이터 마크·data-viz(R6 추가)**: 데이터도 토큰화 = data=정체성(Lupi 'institutional lens'·skill §6 generative 확장). ★시퀀셜=단일 hue 명도 변주=본질 CVD-safe(명도는 모든 색각이상서 보존)·확률/강도에 최적. 카테고리=Wong/ColorBrewer ≤6 + ★색 단독 인코딩 금지(WCAG 1.4.1=shape/선스타일/직접라벨 병행·CVD 시뮬 ≥3). monochrome 브랜드는 다색보다 명도+shape가 on-brand+CVD-safe. ★불확실성 정직 인코딩(false precision 금지)=점추정 단독 금지·신뢰구간/fan 밴드(시간경과 확산)·HOP(가능결과 애니=불확실성 체감·reduced-motion 정적등가)·명도/투명도=확률. ★a11y 백본=백킹 데이터테이블이 진실(차트=그 시각화·노출 table 또는 aria-describedby)·APCA 대비(다크)·200% 리사이즈. chrome 라벨=muted(faint 금지=소형 약함[[atlas-typography-system-r5]] APCA). 근거=Carbon/Cloudscape·FlowingData/Bank of England fan·A11Y Collective.
8. master 승인(신규 토큰 정책·스킬 등록)은 feed push로 보고.

## 주의할 점 (함정 — 겪을 때마다 한 줄씩 누적)
- ★CSS 주석 본문의 `*/` 시퀀스(예 `--font-*/--radius`)가 주석을 조기 종료→그 뒤 `:root` 토큰 전멸→흰배경 렌더. 육안 소스리뷰로 안 보임. (feedback_css-comment-star-slash-kills-root-tokens)
- WCAG2 "AA 통과"는 다크모드서 거짓 안심(과대평가). APCA Lc로 재검증. 고채도 적/네온은 특히 위험.
- flat `:root`에 리터럴 중복(같은 hex 2곳)=드리프트. 테마서 raw 재선언=팔레트 평행복사(유지보수 폭탄).
- 그리드를 "보이는 라인"으로만 그리고 레이아웃을 지배 안 하면 Swiss의 가독·질서가 안 나옴(장식일 뿐).
- 도메인 다이어그램이 아무 실데이터도 안 담으면 Lupi가 거부한 "cosmetic retouch"(신뢰 역효과).
- 순흑 배경=halation·elevation 불가. @property 미등록 시 잘못된 var 값이 color-mix 체인 전체를 깸.
- ★폰트 primitive 1순위에 상용·미라이선스 폰트(Neue Haas·Söhne 등)를 두면 디자이너 머신에선 보이나 배포 사이트선 로드 실패→전 헤딩 시스템 폴백(Arial). 폰트게이트(renderedFontFace/glyphCoverage)는 first-family 기준 → 게이트 hard FAIL. 1순위=반드시 실제 self-host/로드되는 폰트. (EZERagent-homepage R5)
- glyphCoverage 게이트는 서브셋 외 글리프(신규 헤딩 카피·심볼 →↗ 등)를 시스템 폴백으로 떨어뜨려 FAIL → 카피/심볼 변경 시 서브셋 재생성(fontTools) 동반.

## 확인하는 방법 (검증 — 겪을 때마다 한 줄씩 누적)
- 주석 균형: `grep -o '/\*' f.css|wc -l` == `grep -o '\*/' f.css|wc -l` (불일치=조기종료/고아).
- 리터럴 위치: hex 리터럴이 PRIMITIVES 밖(SEMANTICS/테마)에 있으면 안 됨(grep `#[0-9A-Fa-f]\{6\}`).
- 대비 계산(붙여 실행): 아래 sRGB 공식으로 모든 텍스트/배경 쌍 ratio 산출, <4.5(본문)·<3(대형)은 수정.
  ```python
  def lin(c):
      cs=c/255; return cs/12.92 if cs<=0.03928 else ((cs+0.055)/1.055)**2.4
  def Lum(h):
      h=h.lstrip('#'); r,g,b=(int(h[i:i+2],16) for i in (0,2,4)); return 0.2126*lin(r)+0.7152*lin(g)+0.0722*lin(b)
  def cr(a,b):
      la,lb=Lum(a),Lum(b); hi,lo=max(la,lb),min(la,lb); return (hi+0.05)/(lo+0.05)
  ```
- 헤드리스 렌더 후 Read로 확인: 흰배경+검은글자=토큰 미적용 신호(주석/괄호 균형부터 의심).
- 다크/라이트 양 테마 각각 렌더해 대비·구조 확인.
- ★CVD(색각이상) 검증(data-viz/색 시리즈): Brettel 1997 시뮬(★linear RGB·정확 행렬=libDaltonLens public domain·Lokno gist 행렬은 저자 자인 부정확=금지)→ΔE76. 시퀀셜=L*(명도) 단조 보존이면 CVD-safe 확증·카테고리=쌍 ΔE76 <11이면 색만 불충분(shape/라벨 필수). 'CVD-safe' 주장은 박제 전 시뮬로 자기검증(producer≠evaluator). 하네스 예=EZERagent-homepage _cvd_verify.mjs(결정론·무서버).
