// pane 외관의 순수 계산 — 터미널 폰트 조합·역할 신호 점 색.
//
// main.ts의 applyFontFace/setRoleDot는 이 함수들에 배선만 한다(DOM·localStorage는 호출측).
// 순수 함수라 폰트 폴백·역할 변형(worker-2 등)을 결정론으로 회귀 테스트할 수 있다(appearance.test.ts).

// 기본 터미널 폰트 스택 — ★Windows: Latin 등폭폰트(Cascadia Mono/Consolas)를 CJK 폰트보다
// 앞에 둔다. 아니면 Menlo/SF Mono 부재 시 xterm가 셀 폭을 CJK 전각폰트(Noto Sans KR)로 측정해
// Latin 글자가 넓게 벌어진다(자간 이상).
export const DEFAULT_FONT_STACK =
  "Menlo, 'SF Mono', 'Cascadia Mono', Consolas, 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', monospace";

// 선택 폰트를 기본 스택 '앞'에 합성 — 미설치 폰트는 브라우저가 체인 아래로 폴백하고
// CJK 폴백(한글)은 항상 보존된다. null·공백 = 기본 스택 그대로.
export function composeFontFamily(face: string | null): string {
  const f = face?.trim().replace(/['"]/g, "");
  return f ? `'${f}', ${DEFAULT_FONT_STACK}` : DEFAULT_FONT_STACK;
}

// 폰트 선택지(테마 팝오버) — face null = 기본 스택. 미설치 폰트는 합성 폴백으로 무해.
export const FONT_CHOICES: { label: string; face: string | null }[] = [
  { label: "기본값", face: null },
  { label: "Menlo", face: "Menlo" },
  { label: "SF Mono", face: "SF Mono" },
  { label: "Monaco", face: "Monaco" },
  { label: "Cascadia Mono", face: "Cascadia Mono" },
  { label: "Consolas", face: "Consolas" },
  { label: "JetBrains Mono", face: "JetBrains Mono" },
  { label: "D2Coding", face: "D2Coding" },
  { label: "Nanum Gothic Coding", face: "Nanum Gothic Coding" },
  { label: "Courier New", face: "Courier New" },
];

// 역할 → 신호 색 — Control Center(CC_ROLE_COLOR)와 pane 역할 점의 단일 출처.
export const ROLE_COLOR: Record<string, string> = {
  master: "#3b82f6", cso: "#8b5cf6", worker: "#00e676",
  "reviewer-gemini": "#ffa726", "reviewer-codex": "#2dd4bf",
};

// pane 제목 앞 역할 점 색 — 정확 일치 우선, 변형은 접두 매칭(master-2·cso-1·worker-2·reviewer-* —
// overrides.rs·pack.rs의 역할 접두 매칭 관례와 동일), 미지 역할은 회색, 무역할(일반 셸)은 null(점 숨김).
export function roleDotColor(role: string | null | undefined): string | null {
  if (!role) return null;
  if (ROLE_COLOR[role]) return ROLE_COLOR[role];
  if (role.startsWith("master")) return ROLE_COLOR.master;
  if (role.startsWith("cso")) return ROLE_COLOR.cso;
  if (role.startsWith("worker")) return ROLE_COLOR.worker;
  if (role.startsWith("reviewer")) return ROLE_COLOR["reviewer-gemini"];
  return "#64748b";
}
