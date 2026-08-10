// 배경색 커스텀 테마의 순수 계산 — hex 파싱·상대 휘도·가독 대비 전경색 선택.
//
// main.ts의 applyBgColor는 이 함수들에 배선만 한다(DOM·localStorage는 호출측).
// 순수 함수라 어두운 색·밝은 색·경계값을 결정론으로 회귀 테스트할 수 있다(theme.test.ts).

// 기본(다크) 배경·전경 — 하드코딩 리터럴 대신 이 상수를 단일 출처로 참조.
export const DEFAULT_BG = "#0c1210"; // EZER 에메랄드 딥그린 팔레트(style.css --bg와 동기)
export const DARK_FG = "#cfd8d3"; // 어두운 배경용 밝은 글자(style.css --text와 동기)
export const LIGHT_FG = "#1f2328"; // 밝은 배경용 어두운 글자

// "#rrggbb" → [r,g,b] (0-255). 형식이 아니면 null(호출측이 기본색으로 폴백).
// <input type="color">는 항상 6자리 소문자 hex를 준다.
export function hexToRgb(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-fA-F]{6})$/.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// 상대 휘도(0-1): (0.2126R+0.7152G+0.0722B)를 255로 정규화. 파싱 실패 시 0(어둡다고 간주).
export function relativeLuminance(hex: string): number {
  const rgb = hexToRgb(hex);
  if (!rgb) return 0;
  const [r, g, b] = rgb;
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
}

// 배경 위에서 읽히는 전경색 — 휘도>0.5(밝은 배경)면 어두운 글자, 아니면 밝은 글자.
export function readableForeground(hex: string): string {
  return relativeLuminance(hex) > 0.5 ? LIGHT_FG : DARK_FG;
}
