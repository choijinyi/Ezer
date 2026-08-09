#!/usr/bin/env python3
"""워크스페이스 사이드바 폭 드래그·글자 배율 회귀 게이트 (수동 실행 — CI 미배선).

검증 항목 (2026-07-12 오너 요청):
  1. #wsbar 폭이 --wsbar-w 변수로 구동(기본 216px)·#wsbar-drag 핸들 존재.
  2. 핸들 드래그로 폭이 변하고 localStorage(ezer-wsbar-w) 영속·리로드 복원.
  3. 더블클릭=기본폭 복귀.
  4. A−/A＋ 버튼으로 --wsbar-font 배율 증감·영속·클램프(0.8~2.2).
  5. 콘솔 에러 0.
(pane 재적합은 기존 pane별 ResizeObserver→fitPane 경로 + 드래그 종료 refitAllPanes —
 PTY 없는 브라우저 하네스에선 코드 경로가 unittest·리뷰로 커버되므로 여기선 폭·배율만 단언.)

사전: sh ui/build.sh · pip install playwright · playwright install chromium
실행: python3 ui/e2e/wsbar_gate.py   # exit 0 = PASS
"""
import http.server
import socket
import sys
import threading
from pathlib import Path

DIST = Path(__file__).resolve().parent.parent / "dist"
SHIM = """
window.__TAURI__ = {
  core: { invoke: (c,a) => new Promise(()=>{}) },
  event: { listen: (n,h) => Promise.resolve(()=>{}) },
};
"""
failures: list[str] = []

def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        failures.append(msg)

def main() -> int:
    if not (DIST / "index.html").exists():
        print("FAIL: ui/dist 없음 — 먼저 `sh ui/build.sh`")
        return 2
    from playwright.sync_api import sync_playwright
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(DIST), **kw)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 1400, "height": 900})
            pg.add_init_script(SHIM)
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)[:150]))
            url = f"http://127.0.0.1:{port}/index.html"
            pg.goto(url); pg.wait_for_timeout(500)

            w0 = pg.evaluate("document.getElementById('wsbar').getBoundingClientRect().width")
            check(abs(w0 - 216) < 2, f"기본폭 216px (got {w0})")
            check(pg.evaluate("!!document.getElementById('wsbar-drag')"), "드래그 핸들 존재")

            # 최소폭 경계: 크게 왼쪽으로 드래그 → 하한(176) 클램프 + 헤더 1줄 유지(≤40px — 140px 시절 2단 랩 회귀 방지)
            hb0 = pg.evaluate("(() => { const r = document.getElementById('wsbar-drag').getBoundingClientRect(); return {x: r.x + r.width/2, y: r.y + 200}; })()")
            pg.mouse.move(hb0["x"], hb0["y"]); pg.mouse.down()
            pg.mouse.move(hb0["x"] - 300, hb0["y"], steps=6); pg.mouse.up()
            pg.wait_for_timeout(200)
            wmin = pg.evaluate("document.getElementById('wsbar').getBoundingClientRect().width")
            hh = pg.evaluate("document.getElementById('wsbar-head').getBoundingClientRect().height")
            check(abs(wmin - 176) < 2, f"최소폭 클램프 176px (got {wmin})")
            check(hh <= 40, f"최소폭에서 헤더 1줄 유지 ≤40px (got {hh})")
            pg.dblclick("#wsbar-drag"); pg.wait_for_timeout(150)  # 기본폭 복귀 후 본 시나리오 진행

            # 드래그: 216 → +140
            hb = pg.evaluate("(() => { const r = document.getElementById('wsbar-drag').getBoundingClientRect(); return {x: r.x + r.width/2, y: r.y + 200}; })()")
            pg.mouse.move(hb["x"], hb["y"]); pg.mouse.down()
            pg.mouse.move(hb["x"] + 140, hb["y"], steps=8); pg.mouse.up()
            pg.wait_for_timeout(200)
            w1 = pg.evaluate("document.getElementById('wsbar').getBoundingClientRect().width")
            check(abs(w1 - (w0 + 140)) < 4, f"드래그 후 폭 {w0}+140≈{w1}")
            saved = pg.evaluate("localStorage.getItem('ezer-wsbar-w')")
            check(saved and abs(int(saved) - w1) < 4, f"폭 영속 (localStorage={saved})")

            # 리로드 복원
            pg.reload(); pg.wait_for_timeout(400)
            w2 = pg.evaluate("document.getElementById('wsbar').getBoundingClientRect().width")
            check(abs(w2 - w1) < 4, f"리로드 후 폭 복원 ({w2})")

            # 더블클릭 = 기본폭
            pg.dblclick("#wsbar-drag")
            pg.wait_for_timeout(150)
            w3 = pg.evaluate("document.getElementById('wsbar').getBoundingClientRect().width")
            check(abs(w3 - 216) < 2, f"더블클릭 기본폭 복귀 ({w3})")

            # 글자 배율: A＋ ×3 → 1.3, 클램프 상한 2.2
            for _ in range(3):
                pg.click("#btn-ws-font-plus")
            f1 = pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--wsbar-font').trim()")
            check(f1 == "1.3", f"A＋×3 → --wsbar-font=1.3 (got {f1})")
            check(pg.evaluate("localStorage.getItem('ezer-wsbar-font')") == "1.3", "배율 영속")
            for _ in range(20):
                pg.click("#btn-ws-font-plus")
            f2 = pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--wsbar-font').trim()")
            check(f2 == "2.2", f"상한 클램프 2.2 (got {f2})")
            for _ in range(30):
                pg.click("#btn-ws-font-minus")
            f3 = pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--wsbar-font').trim()")
            check(f3 == "0.8", f"하한 클램프 0.8 (got {f3})")

            check(not errs, f"콘솔 pageerror 0건 (got {errs})")
            b.close()
    finally:
        httpd.shutdown()
    print(f"\n{'PASS' if not failures else 'FAIL'} — 실패 {len(failures)}건")
    for f in failures:
        print(f"  ✗ {f}")
    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())
