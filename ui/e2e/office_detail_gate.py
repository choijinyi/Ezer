#!/usr/bin/env python3
"""오피스 3D 직원 디테일 12종 E2E 게이트 (수동 실행 — CI 미배선).

무엇을 검증하나:
  office3d.html 이 계약 v1.1(docs/DESIGN-office-detail-v11.md)의 디테일 12종을
  실제로 렌더·반응하는지. WebGL 화면은 직접 단언 불가하므로 office3d.html 의
  `?debug=1` 훅(window.__officeDebug)이 노출하는 상태 카운터/스냅샷을 단언한다.

구성:
  (a) mock 서버 — office3d.html·/vendor 정적 서빙 + /world(합성: v2 정식 키 2부서
      — 본부 main·부서 dept-a, 의도적 동번호 surface:5 충돌쌍 포함,
      presence 전종·ctx 15/65/95·activity 0.1/0.9·rate·progress·run·blocked·
      kanban 6태스크·review 2건·board 히트+비용) + /stream SSE 각본 프레임
      (progress·runcard failed/succeeded·blocked/unblocked·verdict·doc from→to /
       from null·patch_top kanban/review/board/blocked·patch ctx→critical).
  (b) Playwright(chromium)로 ?debug=1 로드 → 스냅샷·카운터 단언 → 스크린샷.

사전 조건:  pip install playwright && playwright install chromium
실행:      python3 ui/e2e/office_detail_gate.py     # exit 0 = PASS
"""
import http.server
import json
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# /peek 로 서버가 실제 수신한 key 를 기록(② fragment/절단 회귀 방지 — 서버측 기록을 게이트가 검사).
PEEK_KEYS: list[str] = []

WEB_DIR = Path(__file__).resolve().parents[2] / "EZERagent-pack" / "web"
SHOT = Path(__file__).resolve().parent / "office_detail_snapshot.png"
NOW = int(time.time())

# ── 합성 월드 (계약 §2 스키마) ────────────────────────────────────────────
def rate(label, used, resets=None):
    return {"label": label, "used_pct": used, "resets_at": resets or (NOW + 3600)}

def heat_row(base):
    return [round(min(1.0, base + (h % 6) * 0.12), 2) for h in range(24)]

# v2 정식 키 = <dept_slug>@surface:<N>. 부서 dept-a 와 본부 main 이 **의도적으로 동번호 surface:5** 를
# 공유 — 전역 유일성이 dept_slug 접두로 보장됨을 검증한다(diff/엔티티 충돌 회귀 방지).
NODES_DA = [
    {"key": "dept-a@surface:5", "role": "master", "presence": "active", "presence_conf": 0.9,
     "ctx": {"pct": 65}, "activity": 0.9, "agent": "claude", "dept_label": "부서-A",
     "task": "메타버스 오피스 디테일 12종 프론트 구현 및 E2E 게이트 하네스 작성 — 계약 v1.1 준수",
     "rate": [rate("5h", 80)], "flags": [], "idle_secs": 0,
     "progress": {"task": "office-detail", "stage": "구현", "pct": 42, "detail": "링"},
     "run": {"queued": 2, "active": {"task": "build", "started": NOW}, "done_today": 5, "failed_today": 1}},
    {"key": "dept-a@surface:12", "role": "worker", "presence": "waiting", "presence_conf": 0.8,
     "ctx": {"pct": 15}, "activity": 0.1, "agent": "claude", "task": "백엔드 브리지 대기",
     "dept_label": "부서-A", "rate": [], "flags": [], "idle_secs": 0,
     "progress": {"task": "bridge", "stage": "대기", "pct": 10},
     "run": {"queued": 5, "active": None, "done_today": 1, "failed_today": 0}},
    {"key": "dept-a@surface:13", "role": "reviewer-codex", "presence": "drowsy", "presence_conf": 0.7,
     "ctx": {"pct": 95}, "activity": 0.0, "agent": "codex", "task": "리뷰 대기 중 졸음", "dept_label": "부서-A",
     "rate": [rate("5h", 95)], "flags": ["ctx_critical"], "idle_secs": 180, "progress": None, "run": None},
    {"key": "dept-a@surface:14", "role": "reviewer-agy", "presence": "sleeping", "presence_conf": 0.6,
     "ctx": None, "activity": 0.0, "agent": "agy", "task": "수면", "rate": [], "dept_label": "부서-A",
     "flags": [], "idle_secs": 600, "progress": None, "run": None},
    # 적대 키: 불투명 토큰에 fragment 문자(#)를 심어 URL 인코딩 방어를 강제 검증(§4c encodeURIComponent).
    {"key": "dept-a@surface:9#raw", "role": "worker", "presence": "waiting", "presence_conf": 0.8,
     "ctx": None, "activity": 0.0, "agent": "claude", "task": "적대 키(불투명 토큰) 인코딩 검증용",
     "dept_label": "부서-A", "rate": [], "flags": [], "idle_secs": 0, "progress": None, "run": None},
]
NODES_MAIN = [
    {"key": "main@surface:5", "role": "cso", "presence": "quiescing", "presence_conf": 0.9,
     "ctx": {"pct": 95}, "activity": 0.5, "agent": "claude", "task": "컨텍스트 정리", "dept_label": "본부",
     "rate": [], "flags": ["ctx_critical"], "idle_secs": 0, "progress": None, "run": None},
    {"key": "main@surface:22", "role": "worker", "presence": "active", "presence_conf": 0.9,
     "ctx": {"pct": 40}, "activity": 0.7, "agent": "claude", "task": "테스트 작성", "dept_label": "본부",
     "rate": [], "flags": [], "idle_secs": 0, "progress": None,
     "run": {"queued": 1, "active": {"task": "pytest", "started": NOW}, "done_today": 3, "failed_today": 0}},
    {"key": "main@surface:23", "role": "worker", "presence": "dead", "presence_conf": 0.5,
     "ctx": None, "activity": 0.0, "agent": None, "task": "", "rate": [], "dept_label": "본부",
     "flags": [], "idle_secs": 0, "progress": None, "run": None},
    {"key": "main@surface:24", "role": "reviewer-gemini", "presence": "waiting", "presence_conf": 0.8,
     "ctx": {"pct": 72}, "activity": 0.3, "agent": "gemini", "task": "리뷰 준비", "dept_label": "본부",
     "rate": [rate("weekly", 50)], "flags": [], "idle_secs": 0, "progress": None, "run": None},
]

def world():
    return {
        "v": 2, "seq": 1, "daemon": {"version": "0.12.34", "paused": False},
        "departments": [
            {"id": "main", "floor": 2, "nodes": NODES_MAIN},
            {"id": "dept-a", "floor": 1, "nodes": NODES_DA},
        ],
        "lobby": {"unassigned": []}, "server_room": [], "todo": {},
        "blocked": [{"task": "task-A", "blocked_by": ["dept-a@surface:5"], "key": "dept-a@surface:12", "ts": NOW}],
        "kanban": {"ts": NOW, "tasks": [
            {"id": "t1", "title": "게이지 구현", "status": "done", "owner": "master", "blocked_by": []},
            {"id": "t2", "title": "칸반 벽면", "status": "doing", "owner": "master", "blocked_by": []},
            {"id": "t3", "title": "브리지 스캔", "status": "todo", "owner": "worker", "blocked_by": []},
            {"id": "t4", "title": "리뷰 라운드", "status": "blocked", "owner": "worker", "blocked_by": ["t2"]},
            {"id": "t5", "title": "전광판", "status": "todo", "owner": "cso", "blocked_by": []},
            {"id": "t6", "title": "배달 모션", "status": "done", "owner": "worker", "blocked_by": []},
        ]},
        "review": {"ts": NOW, "items": [
            {"reviewer": "codex", "verdict": "REVISE", "target": "office3d", "ts": NOW - 60},
            {"reviewer": "agy", "verdict": "ACCEPT", "target": "office3d", "ts": NOW},
        ]},
        "board": {"heat": {"dept-a@surface:5": heat_row(0.3), "dept-a@surface:12": heat_row(0.1),
                           "main@surface:5": heat_row(0.5)},
                  "cost_today": {"usd": 12.34, "tokens": 456000}},
    }

# ── /stream 각본 (초기 world 후 순차 방출) ──────────────────────────────────
def script():
    return [
        {"t": "world", "world": world()},
        # ① fx는 동번호 dept-a@surface:5 아바타에만 링을 세운다(main@surface:5 무영향).
        {"t": "fx", "kind": "progress", "key": "dept-a@surface:5", "task": "office-detail", "stage": "검증", "pct": 60},
        # ③ 본부 이벤트(main@surface:N)는 본부 노드에 매칭된다.
        {"t": "fx", "kind": "progress", "key": "main@surface:22", "task": "hq", "stage": "구동", "pct": 75},
        {"t": "fx", "kind": "runcard", "key": "dept-a@surface:5", "phase": "failed", "task": "build", "summary": "타입 에러"},
        {"t": "fx", "kind": "runcard", "key": "main@surface:22", "phase": "succeeded", "task": "pytest"},
        {"t": "fx", "kind": "blocked", "task": "task-A", "blocked_by": ["dept-a@surface:5"], "key": "dept-a@surface:12"},
        {"t": "fx", "kind": "unblocked", "task": "task-A", "key": "dept-a@surface:12"},
        {"t": "fx", "kind": "verdict", "reviewer": "codex", "verdict": "BLOCK", "target": "office3d"},
        {"t": "fx", "kind": "doc", "from": "dept-a@surface:5", "to": "dept-a@surface:12", "bytes": 320},   # 같은 층 → 보행 배달
        {"t": "fx", "kind": "doc", "from": None, "to": "dept-a@surface:13", "bytes": 128},                 # from null → 아크
        # ① patch는 동번호 main@surface:5 에만(dept-a@surface:5 ctx 불변).
        {"t": "patch", "key": "main@surface:5", "node": dict(NODES_MAIN[0], ctx={"pct": 33})},
        {"t": "patch_top", "field": "kanban", "value": world()["kanban"]},
        {"t": "patch_top", "field": "review", "value": {"ts": NOW, "items": [
            {"reviewer": "agy", "verdict": "ACCEPT", "target": "office3d", "ts": NOW + 1}]}},
        {"t": "patch_top", "field": "blocked",
         "value": [{"task": "task-A", "blocked_by": ["dept-a@surface:5"], "key": "dept-a@surface:12", "ts": NOW}]},
        {"t": "patch_top", "field": "board", "value": {
            "heat": {"dept-a@surface:5": heat_row(0.6), "main@surface:22": heat_row(0.2)},
            "cost_today": {"usd": 20.01, "tokens": 512000}}},
        {"t": "patch", "key": "dept-a@surface:12", "node": dict(NODES_DA[1], ctx={"pct": 95})},   # ctx→critical
    ]

STOP = threading.Event()

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # 조용히
        pass

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self._json({"ok": True})

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/stream":
            return self._stream()
        if path == "/world":
            return self._json(world())
        if path == "/history":
            return self._json({"events": []})
        if path == "/peek":
            q = parse_qs(urlparse(self.path).query)   # parse_qs 가 percent-decoding 수행 → 정식 키 복원
            PEEK_KEYS.append(q.get("key", [""])[0])
            return self._json({"ok": True, "lines": ["peek 응답 샘플 라인"]})
        # 정적 파일
        rel = "office3d.html" if path in ("/", "") else path.lstrip("/")
        fp = (WEB_DIR / rel).resolve()
        if not str(fp).startswith(str(WEB_DIR)) or not fp.is_file():
            self.send_response(404); self.end_headers(); return
        data = fp.read_bytes()
        ctype = ("text/html" if fp.suffix == ".html"
                 else "application/javascript" if fp.suffix in (".js", ".mjs")
                 else "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            for i, frame in enumerate(script()):
                if STOP.is_set():
                    return
                self.wfile.write(f"data: {json.dumps(frame)}\n\n".encode())
                self.wfile.flush()
                time.sleep(0.4 if i == 0 else 0.25)
            # 연결 유지(EventSource 재접속으로 각본 중복 방지)
            while not STOP.is_set():
                self.wfile.write(b":hb\n\n")
                self.wfile.flush()
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


SNAP = "window.__officeDebug ? window.__officeDebug.snapshot() : null"

failures: list[str] = []
asserted = 0

def check(cond, msg):
    global asserted
    asserted += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        failures.append(msg)

def main() -> int:
    if not (WEB_DIR / "office3d.html").is_file():
        print(f"FAIL: {WEB_DIR}/office3d.html 없음")
        return 2
    from playwright.sync_api import sync_playwright

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    console_errors: list[str] = []
    page_errors: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=[
                "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--use-gl=angle"])
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/office3d.html?debug=1")

            # 월드 구축 대기 (게이지 등장 = addNode 완료 신호)
            page.wait_for_function("(s)=>{const d=eval(s);return d && d.gauges>0}",
                                   arg=SNAP, timeout=8000)
            # 각본 완료 대기 (board patch_top = 마지막 근처)
            page.wait_for_function("(s)=>{const d=eval(s);return d && d.patchTop && d.patchTop.board>0}",
                                   arg=SNAP, timeout=12000)
            page.wait_for_timeout(500)
            # #4 task 전문 — 선택 경로 구동 (v2 정식 키)
            page.evaluate("window.__officeDebug.openPanel('dept-a@surface:5')")
            page.wait_for_timeout(300)

            snap = page.evaluate(SNAP)
            fx = snap["fx"]; pt = snap["patchTop"]
            print("  스냅샷:", json.dumps(snap, ensure_ascii=False))

            check(snap["gauges"] >= 6, f"#1 ctx 게이지 표시 {snap['gauges']}개(≥6, null 노드 제외)")
            check(snap["papers"] >= 5, f"#2 활동 강도 서류 더미 {snap['papers']}장(≥5)")
            check("progress" in fx, "#2 코드 스크롤 활성(활동 노드 존재)")
            check(snap["rateLeds"] >= 3, f"#3 rate LED 표시 {snap['rateLeds']}개(≥3)")
            check(snap["taskTip"] is True, "#4 task 전문 말풍선(선택 시 표시)")
            check(snap["idle"] >= 2, f"#5 방치 시간 스프라이트 {snap['idle']}개(drowsy+sleeping)")
            check(snap["rings"] >= 2 and 60 in [p for p in snap["ringPcts"] if p is not None],
                  f"#6 진행률 링 {snap['rings']}개·fx pct=60 반영 (pcts={snap['ringPcts']})")
            check(snap["ringPulse"] >= 1, f"#6 progress fx 펄스 {snap['ringPulse']}회")
            check(snap["runCards"] >= 8, f"#7 작업 카드 {snap['runCards']}장(큐+활성 ≥8)")
            check(snap["runcardFail"] >= 1 and snap["runcardOk"] >= 1,
                  f"#7 runcard failed={snap['runcardFail']} succeeded={snap['runcardOk']}")
            check(snap["blockedFx"] >= 1 and snap["unblockedFx"] >= 1,
                  f"#8 blocked/unblocked fx = {snap['blockedFx']}/{snap['unblockedFx']}")
            check(snap["blockedArrows"] >= 1, f"#8 의존 점선 {snap['blockedArrows']}개(양측 귀속)")
            check(snap["kanbanCards"] >= 1 and pt.get("kanban", 0) >= 1,
                  f"#9 칸반 카드 {snap['kanbanCards']}장·patch_top kanban={pt.get('kanban',0)}")
            check(snap["verdict"] >= 1 and snap["reviewConvened"] >= 1 and pt.get("review", 0) >= 1,
                  f"#10 리뷰 verdict={snap['verdict']} 집결={snap['reviewConvened']} patch_top review={pt.get('review',0)}")
            check(snap["docFrom"] >= 1 and snap["docNoFrom"] >= 1,
                  f"#11 배달 보행={snap['docFrom']} 아크={snap['docNoFrom']}")
            check(snap["boardTs"] > 0 and pt.get("board", 0) >= 1,
                  f"#12 전광판 갱신 ts={snap['boardTs']}·patch_top board={pt.get('board',0)}")

            # ── v2 부서 한정 키: 동번호 충돌 격리 · 인코딩 · 본부 매칭 · dept_label ──
            da5 = page.evaluate("window.__officeDebug.nodeState('dept-a@surface:5')")
            mn5 = page.evaluate("window.__officeDebug.nodeState('main@surface:5')")
            m22 = page.evaluate("window.__officeDebug.nodeState('main@surface:22')")
            print("  키상태:", json.dumps({"dept-a@surface:5": da5, "main@surface:5": mn5,
                                          "main@surface:22": m22}, ensure_ascii=False))
            # ① fx 격리 — dept-a@surface:5 에만 링, 동번호 main@surface:5 무영향
            check(bool(da5) and da5["ringVisible"] is True,
                  f"① fx progress → dept-a@surface:5 링 표시(정확 타깃) (state={da5})")
            check(bool(mn5) and mn5["ringVisible"] is False,
                  f"① 동번호 main@surface:5 fx 무영향(링 없음) (state={mn5})")
            # ① patch 격리 — main@surface:5 ctx=33 반영, 동번호 dept-a@surface:5 ctx=65 불변
            check(bool(mn5) and mn5["ctx"] == 33,
                  f"① patch → main@surface:5 ctx=33 반영 (state={mn5})")
            check(bool(da5) and da5["ctx"] == 65,
                  f"① 동번호 dept-a@surface:5 ctx=65 불변(patch 비침투) (state={da5})")
            # ③ 본부 이벤트(main@surface:N)가 본부 노드에 매칭
            check(bool(m22) and m22["ringVisible"] is True,
                  f"③ 본부 이벤트 main@surface:22 → 본부 노드 링 매칭 (state={m22})")
            # ② /peek 수신 key == 정식 키 전체 (fragment/절단 회귀 방지 — 서버측 기록 검사)
            page.evaluate("window.__officeDebug.openPanel('dept-a@surface:5')")
            page.evaluate("window.__officeDebug.peek()")
            page.wait_for_timeout(300)
            check(bool(PEEK_KEYS) and PEEK_KEYS[-1] == "dept-a@surface:5",
                  f"② /peek 수신 key == 정식 키 전체 'dept-a@surface:5' (got {PEEK_KEYS[-1] if PEEK_KEYS else None})")
            # ② 적대 키(불투명 토큰 + fragment 문자) 전달 — encodeURIComponent 제거 시 절단되어 FAIL
            page.evaluate("window.__officeDebug.openPanel('dept-a@surface:9#raw')")
            page.evaluate("window.__officeDebug.peek()")
            page.wait_for_timeout(300)
            check(bool(PEEK_KEYS) and PEEK_KEYS[-1] == "dept-a@surface:9#raw",
                  f"② 적대 키 fragment 문자 전달(인코딩 방어) 'dept-a@surface:9#raw' (got {PEEK_KEYS[-1] if PEEK_KEYS else None})")
            # ④ 패널 타이틀 dept_label 표기 — raw 키 비노출
            page.evaluate("window.__officeDebug.openPanel('main@surface:5')")
            page.wait_for_timeout(150)
            title = page.evaluate("window.__officeDebug.panelTitle()")
            check("본부" in title and "@surface" not in title and "main" not in title,
                  f"④ 패널 dept_label 표기('본부 · role', raw 키 비노출) (title={title!r})")

            check(len(page_errors) == 0, f"콘솔 pageerror 0건 (got {page_errors})")
            check(len(console_errors) == 0, f"콘솔 error 0건 (got {console_errors[:3]})")

            page.screenshot(path=str(SHOT))
            print(f"  스크린샷 저장: {SHOT}")
            browser.close()
    finally:
        STOP.set()
        httpd.shutdown()

    print(f"\n{'PASS' if not failures else 'FAIL'} — 단언 {asserted}종(12기능 각 ≥1) · 실패 {len(failures)}건")
    for f in failures:
        print(f"  ✗ {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
