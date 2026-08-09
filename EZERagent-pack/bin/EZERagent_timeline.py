#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EZERagent_timeline — 편집-결정 IR(edit_decisions.json) 위의 스냅샷-교체 편집 커맨드 + 언두/재현 저널.

에이전트가 타임라인을 *프로그램으로 편집*하는 EZERagent-native API(소켓버스 CLI — 네트워크 MCP 아님).
OpenCut 커맨드 패턴(opencut-classic/apps/web/src/commands/base-command.ts·core/managers/commands.ts:
21-45) 클린룸 이식: 각 편집은 **스냅샷-교체** 커맨드다 — undo()는 저장된 pre-state를 통째로
복원하므로 절대 드리프트하지 않는다(diff-and-patch 아님). 모든 편집은 `<ir>.history.jsonl`에
append되어 **감사·재현(replay)·저렴한 롤백**을 준다(producer≠evaluator: agy·codex가 편집열을
replay·diff). 시간은 정수 틱(W0-2 edit_decisions.schema.json, TICKS_PER_SECOND=120000)이 진실.

정직 경계: undo는 IR(작은 JSON) 롤백만 저렴하다 — 렌더된 mp4 재사용 회피는 콘텐츠-주소 캐시가
전제인 별도 후속 작업이다(여기서 약속하지 않는다). 구조 스키마 검증은 check_timeline.py validate
소관(이 도구는 편집 연산·저널만). 결과 IR은 edit_decisions 스키마에 부합하게 유지한다.

사용:
    python3 EZERagent_timeline.py init   --file F --fps N --render-runtime R
    python3 EZERagent_timeline.py insert --file F --track KIND --id ID --in T --out T \
            [--intended T] [--mode M] [--transition X] [--source S]
    python3 EZERagent_timeline.py move   --file F --id ID --to T              # in=T, 길이 보존(시프트)
    python3 EZERagent_timeline.py trim   --file F --id ID [--in T] [--out T]  # in/out 직접 설정
    python3 EZERagent_timeline.py split  --file F --id ID --at T              # at에서 분할(스팬 보존·snap-once)
    python3 EZERagent_timeline.py remove --file F --id ID
    python3 EZERagent_timeline.py undo   --file F                             # 마지막 편집 스냅샷 복원
    python3 EZERagent_timeline.py show   --file F [--json]
    python3 EZERagent_timeline.py --self-test
종료 코드: 0 성공 · 1 편집 오류(id 없음·undo 빈 저널·in≥out·at 범위밖 등) · 2 인자/입출력/JSON 오류.
의존성: 파이썬 표준 라이브러리만(네트워크·LLM 없음·결정론).
"""

import argparse
import json
import os
import sys
import tempfile

TICKS_PER_SECOND = 120_000
TRACK_KINDS = ("avatar", "broll", "graphic", "caption", "audio", "music")


def fail(code, msg):
    print(json.dumps({"error": msg}, ensure_ascii=False), file=sys.stderr)
    return code


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def history_path(ir_path):
    """<ir>.json → <ir>.history.jsonl (편집 저널 — 스냅샷-교체 언두/재현)."""
    base = ir_path[:-5] if ir_path.endswith(".json") else ir_path
    return base + ".history.jsonl"


def load_ir(path):
    """(ir, err_code, err_msg). 성공 시 (ir, None, None)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None, None
    except FileNotFoundError:
        return None, 2, "IR 파일 없음: %s (init으로 생성)" % path
    except (OSError, json.JSONDecodeError) as e:
        return None, 2, "IR 로드 실패: %s (%s)" % (path, e)


def write_atomic(path, obj):
    """tmp 기록 후 os.replace로 원자 교체(실행 중 부분 기록 방지)."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".jtl-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def all_elements(ir):
    """(track, element) 쌍을 순회 — id 탐색용."""
    for tr in ir.get("tracks", []) or []:
        if isinstance(tr, dict):
            for el in tr.get("elements", []) or []:
                if isinstance(el, dict):
                    yield tr, el


def find_element(ir, el_id):
    for tr, el in all_elements(ir):
        if el.get("id") == el_id:
            return tr, el
    return None, None


def append_history(ir_path, op, args, pre_snapshot):
    """편집 저널에 한 줄 append — pre 스냅샷 전체를 담아 undo가 통째로 복원한다(스냅샷-교체)."""
    hp = history_path(ir_path)
    seq = 0
    if os.path.exists(hp):
        with open(hp, encoding="utf-8") as f:
            seq = sum(1 for _ in f)
    rec = {"seq": seq, "op": op, "args": args, "pre": pre_snapshot}
    with open(hp, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _snapshot(ir):
    """깊은 복제 스냅샷(JSON 라운드트립 — 공유 참조로 인한 사후 변형 차단)."""
    return json.loads(json.dumps(ir))


# ── 커맨드 ──
def cmd_init(args):
    if os.path.exists(args.file):
        return fail(2, "이미 존재: %s (덮어쓰지 않음)" % args.file)
    fps = args.fps
    try:
        fps_val = int(fps)
    except (TypeError, ValueError):
        fps_val = fps  # "30000/1001" 같은 문자열 허용(검증은 check_timeline.py)
    ir = {"schema_version": 1, "render_runtime": args.render_runtime,
          "fps": fps_val, "tracks": []}
    write_atomic(args.file, ir)
    print(json.dumps({"ok": True, "init": args.file}, ensure_ascii=False))
    return 0


def cmd_insert(args):
    ir, ec, em = load_ir(args.file)
    if ec:
        return fail(ec, em)
    if args.track not in TRACK_KINDS:
        return fail(2, "track kind 무효: %s — %s" % (args.track, "|".join(TRACK_KINDS)))
    if not _is_int(args.inn) or not _is_int(args.out) or args.out <= args.inn:
        return fail(1, "in/out 정수 틱·out>in 필요(in=%s out=%s)" % (args.inn, args.out))
    if find_element(ir, args.id)[1] is not None:
        return fail(1, "id 중복: %s" % args.id)
    pre = _snapshot(ir)
    el = {"id": args.id, "in_ticks": args.inn, "out_ticks": args.out}
    if args.intended is not None:
        el["intended_ticks"] = args.intended
    if args.mode:
        el["mode"] = args.mode
    if args.transition:
        el["transition"] = args.transition
    if args.source:
        el["source"] = args.source
    track = next((tr for tr in ir["tracks"] if tr.get("kind") == args.track), None)
    if track is None:
        track = {"kind": args.track, "elements": []}
        ir["tracks"].append(track)
    track.setdefault("elements", []).append(el)
    append_history(args.file, "insert", {"track": args.track, "id": args.id}, pre)
    write_atomic(args.file, ir)
    print(json.dumps({"ok": True, "op": "insert", "id": args.id, "track": args.track}, ensure_ascii=False))
    return 0


def cmd_move(args):
    ir, ec, em = load_ir(args.file)
    if ec:
        return fail(ec, em)
    if not _is_int(args.to) or args.to < 0:
        return fail(1, "--to 0 이상 정수 틱 필요(%s)" % args.to)
    _, el = find_element(ir, args.id)
    if el is None:
        return fail(1, "id 없음: %s" % args.id)
    if not (_is_int(el.get("in_ticks")) and _is_int(el.get("out_ticks"))):
        return fail(1, "%s 의 in/out_ticks 가 정수 아님" % args.id)
    pre = _snapshot(ir)
    dur = el["out_ticks"] - el["in_ticks"]  # 길이 보존 시프트
    el["in_ticks"] = args.to
    el["out_ticks"] = args.to + dur
    append_history(args.file, "move", {"id": args.id, "to": args.to}, pre)
    write_atomic(args.file, ir)
    print(json.dumps({"ok": True, "op": "move", "id": args.id,
                      "in_ticks": el["in_ticks"], "out_ticks": el["out_ticks"]}, ensure_ascii=False))
    return 0


def cmd_trim(args):
    ir, ec, em = load_ir(args.file)
    if ec:
        return fail(ec, em)
    if args.inn is None and args.out is None:
        return fail(2, "--in 또는 --out 중 하나는 필요")
    _, el = find_element(ir, args.id)
    if el is None:
        return fail(1, "id 없음: %s" % args.id)
    new_in = args.inn if args.inn is not None else el.get("in_ticks")
    new_out = args.out if args.out is not None else el.get("out_ticks")
    if not (_is_int(new_in) and _is_int(new_out)) or new_out <= new_in or new_in < 0:
        return fail(1, "in/out 정수 틱·out>in≥0 필요(in=%s out=%s)" % (new_in, new_out))
    pre = _snapshot(ir)
    el["in_ticks"], el["out_ticks"] = new_in, new_out
    append_history(args.file, "trim", {"id": args.id, "in": new_in, "out": new_out}, pre)
    write_atomic(args.file, ir)
    print(json.dumps({"ok": True, "op": "trim", "id": args.id,
                      "in_ticks": new_in, "out_ticks": new_out}, ensure_ascii=False))
    return 0


def cmd_split(args):
    ir, ec, em = load_ir(args.file)
    if ec:
        return fail(ec, em)
    if not _is_int(args.at):
        return fail(1, "--at 정수 틱 필요(%s)" % args.at)
    track, el = find_element(ir, args.id)
    if el is None:
        return fail(1, "id 없음: %s" % args.id)
    a, b = el.get("in_ticks"), el.get("out_ticks")
    if not (_is_int(a) and _is_int(b)):
        return fail(1, "%s 의 in/out_ticks 가 정수 아님" % args.id)
    if not (a < args.at < b):
        return fail(1, "--at(%d)는 in(%d)<at<out(%d) 범위여야 함" % (args.at, a, b))
    new_id = "%s-2" % args.id
    if find_element(ir, new_id)[1] is not None:
        return fail(1, "분할 결과 id 충돌: %s" % new_id)
    pre = _snapshot(ir)
    # snap-once: at이 단일 경계 — 왼쪽 out=at, 오른쪽 in=at (스팬 보존: 좌+우=원본).
    right = dict(el)
    right["id"] = new_id
    right["in_ticks"] = args.at
    right["out_ticks"] = b
    if "intended_ticks" in right:
        del right["intended_ticks"]  # 오른쪽 조각은 의도 큐 비움(원본 진입 큐는 왼쪽 소유)
    el["out_ticks"] = args.at
    track["elements"].append(right)
    append_history(args.file, "split", {"id": args.id, "at": args.at, "new_id": new_id}, pre)
    write_atomic(args.file, ir)
    print(json.dumps({"ok": True, "op": "split", "id": args.id, "new_id": new_id,
                      "at": args.at}, ensure_ascii=False))
    return 0


def cmd_remove(args):
    ir, ec, em = load_ir(args.file)
    if ec:
        return fail(ec, em)
    track, el = find_element(ir, args.id)
    if el is None:
        return fail(1, "id 없음: %s" % args.id)
    pre = _snapshot(ir)
    track["elements"] = [e for e in track["elements"] if e.get("id") != args.id]
    append_history(args.file, "remove", {"id": args.id}, pre)
    write_atomic(args.file, ir)
    print(json.dumps({"ok": True, "op": "remove", "id": args.id}, ensure_ascii=False))
    return 0


def cmd_undo(args):
    hp = history_path(args.file)
    if not os.path.exists(hp):
        return fail(1, "저널 없음 — undo 불가: %s" % hp)
    with open(hp, encoding="utf-8") as f:
        lines = [ln for ln in f.read().split("\n") if ln.strip()]
    if not lines:
        return fail(1, "저널 비어 있음 — undo 불가")
    last = json.loads(lines[-1])
    pre = last.get("pre")
    if pre is None:
        return fail(1, "마지막 저널 항목에 pre 스냅샷 없음(손상)")
    write_atomic(args.file, pre)  # 스냅샷-교체: pre를 통째로 복원
    with open(hp, "w", encoding="utf-8") as f:  # 마지막 항목 제거
        if lines[:-1]:
            f.write("\n".join(lines[:-1]) + "\n")
    print(json.dumps({"ok": True, "op": "undo", "undid": last.get("op"),
                      "remaining": len(lines) - 1}, ensure_ascii=False))
    return 0


def cmd_show(args):
    ir, ec, em = load_ir(args.file)
    if ec:
        return fail(ec, em)
    hp = history_path(args.file)
    hist = 0
    if os.path.exists(hp):
        with open(hp, encoding="utf-8") as f:
            hist = sum(1 for ln in f if ln.strip())
    summary = {"file": args.file, "fps": ir.get("fps"), "render_runtime": ir.get("render_runtime"),
               "tracks": [{"kind": tr.get("kind"), "elements": len(tr.get("elements", []))}
                          for tr in ir.get("tracks", [])],
               "history_depth": hist}
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("timeline %s — fps %s · runtime %s · history %d"
              % (args.file, ir.get("fps"), ir.get("render_runtime"), hist))
        for t in summary["tracks"]:
            print("  %-8s %d elements" % (t["kind"], t["elements"]))
    return 0


# ── self-test ──
def self_test():
    failures = []
    import contextlib
    import io
    sink = io.StringIO()

    class A:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def run(fn, **kw):
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            return fn(A(**kw))

    with tempfile.TemporaryDirectory(prefix="EZERagent-timeline-st-") as td:
        f = os.path.join(td, "edit_decisions.json")
        # init
        if run(cmd_init, file=f, fps=30, render_runtime="hyperframes") != 0:
            failures.append("init exit 0 아님")
        if not os.path.exists(f):
            failures.append("init 파일 미생성")
        # init 재실행 거부
        if run(cmd_init, file=f, fps=30, render_runtime="x") != 2:
            failures.append("기존 파일 init이 거부(exit 2) 아님")
        # insert
        if run(cmd_insert, file=f, track="graphic", id="g1", inn=120000, out=480000,
               intended=120000, mode="left-card", transition=None, source=None) != 0:
            failures.append("insert exit 0 아님")
        # insert 잘못된 track
        if run(cmd_insert, file=f, track="hologram", id="x", inn=0, out=1, intended=None,
               mode=None, transition=None, source=None) != 2:
            failures.append("잘못된 track kind가 exit 2 아님")
        # insert out<=in
        if run(cmd_insert, file=f, track="avatar", id="bad", inn=100, out=100, intended=None,
               mode=None, transition=None, source=None) != 1:
            failures.append("out<=in insert가 exit 1 아님")
        # insert 중복 id
        if run(cmd_insert, file=f, track="graphic", id="g1", inn=0, out=100, intended=None,
               mode=None, transition=None, source=None) != 1:
            failures.append("중복 id insert가 exit 1 아님")

        def load():
            return json.load(open(f, encoding="utf-8"))

        # move(길이 보존)
        run(cmd_move, file=f, id="g1", to=240000)
        _, el = find_element(load(), "g1")
        if el["in_ticks"] != 240000 or el["out_ticks"] != 600000:
            failures.append("move 길이 보존 실패: %s" % el)
        # trim
        run(cmd_trim, file=f, id="g1", inn=240000, out=480000)
        _, el = find_element(load(), "g1")
        if el["out_ticks"] != 480000:
            failures.append("trim 실패: %s" % el)
        # split(스팬 보존)
        run(cmd_split, file=f, id="g1", at=360000)
        ir = load()
        _, left = find_element(ir, "g1")
        _, right = find_element(ir, "g1-2")
        if not right or left["out_ticks"] != 360000 or right["in_ticks"] != 360000 or right["out_ticks"] != 480000:
            failures.append("split 스팬 보존 실패: left=%s right=%s" % (left, right))
        # split 범위 밖
        if run(cmd_split, file=f, id="g1", at=999999) != 1:
            failures.append("범위밖 split이 exit 1 아님")
        # undo(split 되돌림 → g1-2 사라지고 g1.out=480000 복원)
        run(cmd_undo, file=f)
        ir = load()
        if find_element(ir, "g1-2")[1] is not None:
            failures.append("undo가 split을 되돌리지 못함(g1-2 잔존)")
        _, el = find_element(ir, "g1")
        if el["out_ticks"] != 480000:
            failures.append("undo 후 g1 복원 실패: %s" % el)
        # remove + undo 복원
        run(cmd_remove, file=f, id="g1")
        if find_element(load(), "g1")[1] is not None:
            failures.append("remove 실패")
        run(cmd_undo, file=f)
        if find_element(load(), "g1")[1] is None:
            failures.append("undo가 remove를 복원하지 못함")
        # id 없는 op → exit 1
        if run(cmd_move, file=f, id="nope", to=0) != 1:
            failures.append("없는 id move가 exit 1 아님")
        # 저널 소진까지 undo, 빈 저널 undo → exit 1
        for _ in range(20):
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                if cmd_undo(A(file=f)) != 0:
                    break
        if run(cmd_undo, file=f) != 1:
            failures.append("빈 저널 undo가 exit 1 아님")
        # show
        if run(cmd_show, file=f, json=True) != 0:
            failures.append("show exit 0 아님")

    print(json.dumps({"self_test": "ok" if not failures else "fail",
                      "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(description="편집-결정 IR 스냅샷-교체 편집 커맨드 + 언두 저널")
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("init", help="빈 IR 생성")
    p.add_argument("--file", required=True)
    p.add_argument("--fps", required=True)
    p.add_argument("--render-runtime", required=True, dest="render_runtime")

    p = sub.add_parser("insert", help="element 삽입")
    p.add_argument("--file", required=True)
    p.add_argument("--track", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--in", required=True, type=int, dest="inn")
    p.add_argument("--out", required=True, type=int)
    p.add_argument("--intended", type=int, default=None)
    p.add_argument("--mode", default=None)
    p.add_argument("--transition", default=None)
    p.add_argument("--source", default=None)

    p = sub.add_parser("move", help="element 시프트(길이 보존)")
    p.add_argument("--file", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--to", required=True, type=int)

    p = sub.add_parser("trim", help="element in/out 직접 설정")
    p.add_argument("--file", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--in", type=int, default=None, dest="inn")
    p.add_argument("--out", type=int, default=None)

    p = sub.add_parser("split", help="element 분할(스팬 보존·snap-once)")
    p.add_argument("--file", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--at", required=True, type=int)

    p = sub.add_parser("remove", help="element 제거")
    p.add_argument("--file", required=True)
    p.add_argument("--id", required=True)

    p = sub.add_parser("undo", help="마지막 편집 스냅샷 복원")
    p.add_argument("--file", required=True)

    p = sub.add_parser("show", help="IR 요약")
    p.add_argument("--file", required=True)
    p.add_argument("--json", action="store_true")

    args = ap.parse_args()
    if args.self_test:
        return self_test()
    dispatch = {"init": cmd_init, "insert": cmd_insert, "move": cmd_move, "trim": cmd_trim,
                "split": cmd_split, "remove": cmd_remove, "undo": cmd_undo, "show": cmd_show}
    if args.cmd in dispatch:
        return dispatch[args.cmd](args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
