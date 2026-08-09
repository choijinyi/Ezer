#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SESSION_STATE 예약 엔티티 ensure-X (T3-5).

penpot ensure-hidden-theme 패턴의 *개념만* 클린룸 차용 — Clojure 코드복사 0(MPL-2.0 파일전염
회피, well-known idempotent upsert는 보호 대상 아님). 복원 핵심 필드(restore_pointer·open_gates)를
부재 시 idempotent 생성하고, ensure-then-verify 라운드트립으로 그 존재·파싱가능을 결정론 보장한다
(hide≠lose 가드 — 숨김이 손실이 되지 않게).

★R5 FIX: verify는 substring 매칭이 아니라 STRUCTURAL 파싱(블록 구조를 파싱해 orphan/corrupt 탐지).
ensure의 corrupt 경로는 DUPLICATE append가 아니라 in-place REPAIR(깨진 블록을 정상 블록으로 교체).

사용:
    EZERagent_session.py ensure [--file PATH]   # exit 0=ensure 완료(생성·무변형·복구), 2=I/O오류
    EZERagent_session.py verify [--file PATH] [--json]
                                            # exit 0=두 예약 필드 정상, 1=불변식 위반, 2=I/O
    EZERagent_session.py --self-test            # exit 0=배터리 ok, 1=fail (JSON 출력)
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

RESERVED_SENTINEL = "__EZERAGENT__RESERVED__"
FIELDS = ("restore_pointer", "open_gates")

# (open_marker, default_body, close_marker) — penpot hidden-theme-name sentinel 등가.
BLOCKS = {
    "restore_pointer": (
        "<!-- EZERAGENT:RESERVED:restore_pointer %s -->" % RESERVED_SENTINEL,
        "- 복원 포인터: (없음)",
        "<!-- /EZERAGENT:RESERVED:restore_pointer -->",
    ),
    "open_gates": (
        "<!-- EZERAGENT:RESERVED:open_gates %s -->" % RESERVED_SENTINEL,
        "## 미해결 게이트\n- (없음)",
        "<!-- /EZERAGENT:RESERVED:open_gates -->",
    ),
}


def _open_re(field):
    # open 마커는 sentinel 토큰을 반드시 보유해야 정상(R5: sentinel 없는 마커 = corrupt).
    return re.compile(
        r"<!--\s*EZERAGENT:RESERVED:%s\s+%s\s*-->" % (re.escape(field), re.escape(RESERVED_SENTINEL))
    )


def _close_re(field):
    return re.compile(r"<!--\s*/EZERAGENT:RESERVED:%s\s*-->" % re.escape(field))


def _scan(text, field):
    """STRUCTURAL 파싱(R5): 블록 상태를 분류한다.

    반환: ('absent'|'ok'|'corrupt', span) — span은 복구가 교체할 (start,end) 또는 None.
      - absent : open/close 둘 다 없음 → ensure가 새로 생성.
      - corrupt: open만 / close만 / 순서뒤집힘 / 중복(orphan stranded) → ensure가 in-place 교체.
      - ok     : 정상 1쌍(open … close) → 무변형.
    """
    opens = list(_open_re(field).finditer(text))
    closes = list(_close_re(field).finditer(text))
    if not opens and not closes:
        return ("absent", None)
    # 정확히 1쌍이고 open이 close보다 앞 → 정상.
    if len(opens) == 1 and len(closes) == 1 and opens[0].start() < closes[0].start():
        return ("ok", (opens[0].start(), closes[0].end()))
    # 그 외 전부 corrupt(open-only/close-only/중복/역순). 복구 교체 범위 = 마커들의 최소~최대 스팬.
    marks = [m.span() for m in opens] + [m.span() for m in closes]
    start = min(s for s, _ in marks)
    end = max(e for _, e in marks)
    return ("corrupt", (start, end))


def verify_text(text):
    """STRUCTURAL 채점 — substring 아님. orphan/corrupt를 위반으로 잡는다."""
    fields = {}
    violations = []
    for f in FIELDS:
        st, _ = _scan(text, f)
        fields[f] = st == "ok"
        if st == "absent":
            violations.append("예약 필드 '%s' 부재" % f)
        elif st == "corrupt":
            violations.append("예약 필드 '%s' 마커 깨짐(orphan/중복/역순)" % f)
    return {"ok": not violations, "fields": fields, "violations": violations}


def _block_text(field):
    o, body, c = BLOCKS[field]
    return "%s\n%s\n%s" % (o, body, c)


def ensure_text(text):
    """penpot (if (contains? data X) data (assoc ...)) 등가 + R5 REPAIR.

    - ok      : 무변형(바이트 보존, idempotent).
    - corrupt : 깨진 스팬을 정상 블록으로 in-place 교체(DUPLICATE append 아님 — orphan 잔류 0).
    - absent  : 말미에 정상 블록 생성.
    """
    for f in FIELDS:
        st, span = _scan(text, f)
        if st == "ok":
            continue
        block = _block_text(f)
        if st == "corrupt":
            start, end = span
            text = text[:start] + block + text[end:]
        else:  # absent
            if text and not text.endswith("\n"):
                text += "\n"
            text += "\n%s\n" % block
    return text


def _write_atomic(path, text):
    """★G1(a): wakeup._write_json_atomic 동형 텍스트판 — tmp→flush→fsync→os.replace.
    SESSION_STATE는 재부팅 복원의 단일 진실이라 크래시 시점의 반쪽 파일이 곧 복원 실패다."""
    tmp = "%s.tmp.%d.%d" % (path, os.getpid(), time.time_ns())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class _FileLock:
    """★G1(b): wakeup._FileLock 이식 — mkdir 원자성 락. stale(30초+)은 rename으로 원자 회수."""

    def __init__(self, path, timeout=5.0, stale_sec=30.0):
        self.path, self.timeout, self.stale_sec = path, timeout, stale_sec

    def __enter__(self):
        deadline = time.time() + self.timeout
        parent = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(parent, exist_ok=True)
        while True:
            try:
                os.mkdir(self.path)
                return self
            except FileExistsError:
                try:
                    if time.time() - os.stat(self.path).st_mtime > self.stale_sec:
                        os.rename(self.path, "%s.stale.%d" % (self.path, time.time_ns()))
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    raise TimeoutError("lock timeout: %s" % self.path)
                time.sleep(0.02)

    def __exit__(self, *exc):
        try:
            os.rmdir(self.path)
        except OSError:
            pass


def cmd_ensure(path):
    try:
        # ★G1(b): read-modify-write 전체를 배타락으로 직렬화(동시 ensure 경쟁 차단).
        with _FileLock(path + ".lock"):
            text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
            out = ensure_text(text)
            if out != text:  # diff0: 변화 없으면 쓰지 않음(idempotent·mtime 보존)
                # ★G1(c): corrupt 복구는 원문 스팬을 지우므로 교체 전 백업(증거 보존).
                if os.path.isfile(path) and any(_scan(text, f)[0] == "corrupt" for f in FIELDS):
                    shutil.copy2(path, "%s.bak-corrupt-%s" % (path, time.strftime("%Y%m%dT%H%M%S")))
                _write_atomic(path, out)  # ★G1(a): 크래시에도 반쪽 파일 0
            # ensure-then-verify(R5 hide≠lose 가드): 재읽기 후 verify 통과해야 성공.
            re_read = open(path, encoding="utf-8").read()
            return 0 if verify_text(re_read)["ok"] else 2
    except (OSError, TimeoutError):
        return 2


def cmd_verify(path, as_json):
    try:
        r = verify_text(open(path, encoding="utf-8").read())
    except OSError:
        print("읽기 불가: %s" % path, file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["ok"] else 1


def self_test():
    failures = []
    # ① 빈 입력 → 두 필드 정상 생성.
    t = ensure_text("")
    if not verify_text(t)["ok"]:
        failures.append("빈입력 ensure가 필드 미생성")
    # ② idempotent: 정상 파일 2회 적용 바이트 동일(diff0).
    if ensure_text(t) != t:
        failures.append("ensure 비멱등(바이트 변형)")
    # ③ 사용자 산문 보존(블록 내부 채운 내용 무변형).
    user = t.replace("- 복원 포인터: (없음)", "- 복원 포인터: ▶Phase3 게이트2")
    if ensure_text(user) != user:
        failures.append("사용자 내용 보존 실패")
    # ④ corrupt-recover 배터리(R5 핵심): close 마커 제거 → verify FAIL → ensure REPAIR → verify PASS.
    #    그리고 복구가 DUPLICATE가 아닌 in-place 교체임을 증명(마커 쌍이 정확히 1개).
    broken = t.replace("<!-- /EZERAGENT:RESERVED:open_gates -->", "", 1)
    if verify_text(broken)["ok"]:
        failures.append("corrupt(close 제거) 미탐지 — verify가 hollow(substring)")
    repaired = ensure_text(broken)
    if not verify_text(repaired)["ok"]:
        failures.append("corrupt 복구 후 verify 실패(REPAIR 미작동)")
    if len(_open_re("open_gates").findall(repaired)) != 1 \
            or len(_close_re("open_gates").findall(repaired)) != 1:
        failures.append("복구가 DUPLICATE append(마커 중복 — orphan stranded)")
    # ⑤ orphan(open만 떠도는 sentinel) → corrupt 탐지 + 복구.
    orphan = "<!-- EZERAGENT:RESERVED:restore_pointer %s -->\n없는 close" % RESERVED_SENTINEL
    if verify_text(orphan)["fields"]["restore_pointer"]:
        failures.append("open-only orphan을 ok로 오판")
    print(json.dumps(
        {"self_test": "ok" if not failures else "fail", "failures": failures},
        ensure_ascii=False, indent=2,
    ))
    return 0 if not failures else 1


def _default_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "round", "SESSION_STATE.md")


def main():
    ap = argparse.ArgumentParser(description="SESSION_STATE 예약 엔티티 ensure/verify")
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("ensure", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--file", default=None)
        if name == "verify":
            p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    path = (a.file or _default_path()) if a.cmd else _default_path()
    if a.cmd == "ensure":
        return cmd_ensure(path)
    if a.cmd == "verify":
        return cmd_verify(path, getattr(a, "json", False))
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
