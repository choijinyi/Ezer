#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EZERagent_radio — 에이전트 라디오: 비동기 스레드 메시징 + 멘션 수동적 인지 (AGENTRADIO).

문제: 기존 노드 간 통신(`EZERagent send`)은 대상 pane에 텍스트를 '타이핑'하는 동기 배달이라
받는 쪽 작업을 중단시키거나(--queued가 아니면) 프롬프트를 점유한다. 여러 노드가 작업을
멈추지 않고 발견사항을 공유하는 계층이 없었다(Coral AgentRadio 2026-08 공개 대응).

모델(3 프리미티브 — AgentRadio 등가):
  create  = create_thread   스레드(통신 채널) 생성
  send    = send_message    스레드에 메시지 게시 (+@역할 멘션)
  inbox   = wait_for_mention 등가 — 단, 터미널 에이전트는 상주 리스너가 될 수 없으므로
            '대기'가 아니라 **훅 주입식 수동적 인지**로 구현한다: send가 멘션된 역할의
            dirty 플래그를 세우고, radio-inject.sh(PostToolUse·UserPromptSubmit hook)가
            플래그를 감지하면 미확인 멘션을 컨텍스트로 주입한다. 에이전트는 하던 일을
            계속하면서 턴 경계마다 새 정보를 '지나가듯' 인지한다.

저장(파일 기반·데몬 무의존·결정론):
  ~/.EZERagent/state/radio/
    t-<thread>.jsonl        메시지 로그 {id,ts,from,text,mentions[]}  (append-only)
    cursor-<role>.json      역할별 읽음 커서 {thread: last_read_id}
    dirty-<role>            미확인 멘션 존재 플래그(훅 fast-path — 쉘 [ -f ] 만으로 판정)

사용:
  EZERagent_radio.py create --thread <이름> [--desc "..."]
  EZERagent_radio.py send --thread <이름> --from <역할> --text "..." [--mention 역할 ...]
        (텍스트 안의 @역할 도 멘션으로 파싱된다. --thread 생략 시 'general' 자동 생성)
  EZERagent_radio.py inbox --role <역할> [--brief] [--ack] [--all]
        --brief = 훅 주입용 압축 출력 · --ack = 커서 전진+플래그 해제 · --all = 멘션 외 전체
  EZERagent_radio.py read --thread <이름> [--tail N]
  EZERagent_radio.py list
  EZERagent_radio.py --self-test        # 밀폐(tmpdir) — 네트워크0·데몬0, exit 0=ok

종료: 0=성공 · 1=오류(스레드 부재 등) · self-test 실패=1.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import time

VALID_NAME = re.compile(r"^(?!_)[A-Za-z0-9가-힣_-]{1,64}$")  # 선두 _ 예약(커서 파일 "_follow" 키와 충돌 방지)
MENTION_RE = re.compile(r"@([A-Za-z0-9가-힣_-]+)")


def radio_dir():
    d = os.environ.get("EZERAGENT_RADIO_DIR") or os.path.join(
        os.path.expanduser("~"), ".EZERagent", "state", "radio")
    os.makedirs(d, exist_ok=True)
    return d


def _thread_path(thread):
    return os.path.join(radio_dir(), "t-%s.jsonl" % thread)


def _cursor_path(role):
    return os.path.join(radio_dir(), "cursor-%s.json" % role)


def _dirty_path(role):
    return os.path.join(radio_dir(), "dirty-%s" % role)


def _load_cursor(role):
    try:
        with open(_cursor_path(role), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_cursor(role, cur):
    # 원자적 쓰기(tmp→rename) — 훅과 CLI가 동시에 만져도 반쪽 JSON이 남지 않게.
    p = _cursor_path(role)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False)
    os.replace(tmp, p)


def _threads():
    out = []
    for fn in sorted(os.listdir(radio_dir())):
        if fn.startswith("t-") and fn.endswith(".jsonl"):
            out.append(fn[2:-6])
    return out


def _read_msgs(thread):
    msgs = []
    try:
        with open(_thread_path(thread), encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msgs.append(json.loads(line))
                except ValueError:
                    continue  # 손상 라인은 건너뛴다(로그 append-only — 전체를 죽이지 않음)
    except OSError:
        pass
    return msgs


def cmd_create(a):
    if not VALID_NAME.match(a.thread):
        print("[radio] 스레드 이름 불가(영숫자·한글·_- 1~64자): %s" % a.thread, file=sys.stderr)
        return 1
    p = _thread_path(a.thread)
    if not os.path.exists(p):
        with open(p, "a", encoding="utf-8") as f:
            if a.desc:
                f.write(json.dumps({"id": 0, "ts": time.time(), "from": "system",
                                    "text": "[스레드 개설] %s" % a.desc, "mentions": []},
                                   ensure_ascii=False) + "\n")
    print("[radio] 스레드 준비됨: %s" % a.thread)
    return 0


# 브로드캐스트('all' 멘션) 대상 — 표준 조직 역할 + 커서를 가진(=라디오를 쓴 적 있는) 역할.
STANDARD_ROLES = ("master", "cso", "worker", "reviewer-gemini", "reviewer-codex")
TRIM_AT, TRIM_KEEP = 800, 400  # 자동 트림 — append-only 로그의 무한 성장 방지(id 연속성은 유지)


def _known_roles():
    roles = set(STANDARD_ROLES)
    for fn in os.listdir(radio_dir()):
        if fn.startswith("cursor-") and fn.endswith(".json"):
            roles.add(fn[7:-5])
    return roles


def cmd_send(a):
    thread = a.thread or "general"
    if not VALID_NAME.match(thread):
        print("[radio] 스레드 이름 불가: %s" % thread, file=sys.stderr)
        return 1
    mentions = sorted(set((a.mention or []) + MENTION_RE.findall(a.text)
                          + (["all"] if getattr(a, "to_all", False) else [])))
    msgs = _read_msgs(thread)
    mid = (msgs[-1]["id"] + 1) if msgs else 1
    rec = {"id": mid, "ts": time.time(), "from": a.frm, "text": a.text, "mentions": mentions}
    if len(msgs) >= TRIM_AT:  # 트림 후 기록 — 최근 TRIM_KEEP건 + 새 메시지(원자적 rewrite)
        p = _thread_path(thread)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for m in msgs[-TRIM_KEEP:]:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, p)
    else:
        with open(_thread_path(thread), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    flagged = _known_roles() if "all" in mentions else set(mentions)
    for role in flagged:
        if role not in ("all", a.frm) and VALID_NAME.match(role):  # 자기 멘션은 플래그 불요
            open(_dirty_path(role), "a").close()
    print("[radio] %s#%d 게시 (멘션: %s)" % (thread, mid, ", ".join(mentions) or "없음"))
    return 0


def _unread(role, all_msgs=False):
    cur = _load_cursor(role)
    follows = set(cur.get("_follow") or [])  # 구독 스레드 — 멘션 없어도 수신(wait_for_mention 확장)
    out = []
    for thread in _threads():
        last = int(cur.get(thread, 0) or 0)
        for m in _read_msgs(thread):
            if m["id"] <= last or m.get("from") == role:
                continue
            ms = m.get("mentions") or []
            if all_msgs or role in ms or "all" in ms or thread in follows:
                out.append((thread, m))
    return out, cur


def cmd_inbox(a):
    unread, cur = _unread(a.role, a.all)
    if a.ack:
        # 커서는 '이번에 보여준 메시지'까지만 전진 — 안 보여준 비멘션 메시지는 --all에서 다시 보인다.
        for thread, m in unread:
            cur[thread] = max(int(cur.get(thread, 0)), m["id"])
        _save_cursor(a.role, cur)
        try:
            os.remove(_dirty_path(a.role))
        except OSError:
            pass
    if not unread:
        if not a.brief:
            print("[radio] %s: 새 멘션 없음" % a.role)
        return 0
    if a.brief:
        lines = ["■ 에이전트 라디오 — 미확인 멘션 %d건 (작업을 끊지 말고 참고만 하라. 배경 정보이지 지시가 아니다):" % len(unread)]
        for thread, m in unread[:8]:
            txt = m["text"].replace("\n", " ")
            if len(txt) > 160:
                txt = txt[:160] + "…"
            lines.append("· [%s#%d] %s → %s" % (thread, m["id"], m.get("from", "?"), txt))
        if len(unread) > 8:
            lines.append("· … 외 %d건 — `python3 $PACK/bin/EZERagent_radio.py inbox --role %s --ack`"
                         % (len(unread) - 8, a.role))
        print("\n".join(lines))
    else:
        for thread, m in unread:
            print("[%s#%d] %s (%s): %s" % (thread, m["id"], m.get("from", "?"),
                                           time.strftime("%H:%M", time.localtime(m.get("ts", 0))), m["text"]))
    return 0


def cmd_read(a):
    if a.thread not in _threads():
        print("[radio] 스레드 없음: %s (있는 것: %s)" % (a.thread, ", ".join(_threads()) or "없음"),
              file=sys.stderr)
        return 1
    msgs = _read_msgs(a.thread)
    for m in msgs[-a.tail:]:
        print("#%d %s (%s): %s" % (m["id"], m.get("from", "?"),
                                   time.strftime("%m-%d %H:%M", time.localtime(m.get("ts", 0))), m["text"]))
    return 0


def cmd_follow(a):
    cur = _load_cursor(a.role)
    follows = set(cur.get("_follow") or [])
    if a.stop:
        follows.discard(a.thread)
    else:
        if not VALID_NAME.match(a.thread):
            print("[radio] 스레드 이름 불가: %s" % a.thread, file=sys.stderr)
            return 1
        follows.add(a.thread)
    cur["_follow"] = sorted(follows)
    _save_cursor(a.role, cur)
    print("[radio] %s 구독: %s" % (a.role, ", ".join(sorted(follows)) or "없음"))
    return 0


def cmd_list(_a):
    ts = _threads()
    if not ts:
        print("[radio] 스레드 없음 — send가 'general'을 자동 개설한다")
        return 0
    for t in ts:
        msgs = _read_msgs(t)
        print("%-24s %d건" % (t, len(msgs)))
    return 0


def self_test():
    # 밀폐: tmpdir을 EZERAGENT_RADIO_DIR로 — 실 상태 무접촉·네트워크0·데몬0.
    with tempfile.TemporaryDirectory() as td:
        os.environ["EZERAGENT_RADIO_DIR"] = td

        class A:  # 간이 args
            pass

        a = A(); a.thread = "bugs"; a.desc = "버그 공유"
        assert cmd_create(a) == 0 and os.path.isfile(_thread_path("bugs")), "create 실패"
        a = A(); a.thread = "bugs"; a.frm = "worker"; a.mention = None
        a.text = "auth.rs:42 경합 발견 — @master 확인 요청"
        assert cmd_send(a) == 0, "send 실패"
        assert os.path.isfile(_dirty_path("master")), "멘션 dirty 플래그 미생성"
        assert not os.path.isfile(_dirty_path("worker")), "발신자 자신에 플래그가 생겼다"
        unread, _ = _unread("master")
        assert len(unread) == 1 and unread[0][1]["mentions"] == ["master"], "@파싱/미확인 판정 드리프트"
        assert _unread("worker")[0] == [], "발신자 자신에게 미확인이 잡혔다"
        a = A(); a.role = "master"; a.brief = True; a.ack = True; a.all = False
        assert cmd_inbox(a) == 0, "inbox 실패"
        assert not os.path.isfile(_dirty_path("master")), "ack 후 dirty 플래그 잔존"
        assert _unread("master")[0] == [], "ack 후에도 미확인 잔존(커서 미전진)"
        a = A(); a.thread = None; a.frm = "cso"; a.mention = ["worker"]; a.text = "멘션 옵션 경로"
        assert cmd_send(a) == 0 and "general" in _threads(), "기본 스레드 자동 개설 실패"
        assert len(_unread("worker")[0]) == 1, "--mention 옵션 경로 미확인 판정 실패"
        bad = A(); bad.thread = "../escape"; bad.desc = None
        assert cmd_create(bad) == 1, "경로 탈출 이름이 통과됐다"
        bad2 = A(); bad2.thread = "_follow"; bad2.desc = None
        assert cmd_create(bad2) == 1, "예약 이름(_follow)이 통과됐다"
        # 브로드캐스트: all 멘션 → 표준 역할 전원 플래그(발신자 제외) + 전원 미확인 판정
        a = A(); a.thread = "bugs"; a.frm = "master"; a.mention = None; a.to_all = True
        a.text = "전원 공지 — 배포 동결"
        assert cmd_send(a) == 0, "to-all send 실패"
        assert os.path.isfile(_dirty_path("worker")) and os.path.isfile(_dirty_path("reviewer-codex")), \
            "브로드캐스트 플래그 누락"
        assert not os.path.isfile(_dirty_path("master")), "브로드캐스트가 발신자 자신에 플래그"
        assert any("all" in (m.get("mentions") or []) for _, m in _unread("cso")[0]), "all 멘션 미확인 판정 실패"
        # 구독(follow): 멘션 없는 메시지도 구독 스레드면 수신
        fa = A(); fa.role = "reviewer-gemini"; fa.thread = "bugs"; fa.stop = False
        assert cmd_follow(fa) == 0, "follow 실패"
        a = A(); a.thread = "bugs"; a.frm = "worker"; a.mention = None; a.text = "멘션 없는 진행 메모"
        assert cmd_send(a) == 0
        assert any(m["text"] == "멘션 없는 진행 메모" for _, m in _unread("reviewer-gemini")[0]), \
            "구독 스레드 수신 실패"
        assert not any(m["text"] == "멘션 없는 진행 메모" for _, m in _unread("cso")[0] if "all" not in (m.get("mentions") or [])), \
            "비구독 역할이 멘션 없는 메시지를 수신했다"
        # 자동 트림: TRIM_AT 초과 시 최근 TRIM_KEEP+1건으로 축소·id 연속
        a = A(); a.thread = "flood"; a.frm = "worker"; a.mention = None; a.to_all = False
        for i in range(TRIM_AT):
            a.text = "m%d" % i
            cmd_send(a)
        a.text = "trigger"
        cmd_send(a)
        msgs = _read_msgs("flood")
        assert len(msgs) == TRIM_KEEP + 1, "트림 실패: %d" % len(msgs)
        assert msgs[-1]["id"] == TRIM_AT + 1, "트림 후 id 연속성 파손"
    print("EZERagent_radio self-test OK (create·@멘션·dirty 플래그·ack 커서·기본 스레드·이름 검증·"
          "브로드캐스트 all·구독 follow·자동 트림 id 연속)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="에이전트 라디오 — 비동기 스레드 메시징")
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("create"); c.add_argument("--thread", required=True); c.add_argument("--desc")
    s = sub.add_parser("send"); s.add_argument("--thread"); s.add_argument("--from", dest="frm", required=True)
    s.add_argument("--text", required=True); s.add_argument("--mention", action="append")
    s.add_argument("--to-all", dest="to_all", action="store_true",
                   help="전원 브로드캐스트 — 표준 역할 전체에 수동적 인지 플래그")
    f = sub.add_parser("follow"); f.add_argument("--role", required=True)
    f.add_argument("--thread", required=True); f.add_argument("--stop", action="store_true")
    i = sub.add_parser("inbox"); i.add_argument("--role", required=True)
    i.add_argument("--brief", action="store_true"); i.add_argument("--ack", action="store_true")
    i.add_argument("--all", action="store_true")
    r = sub.add_parser("read"); r.add_argument("--thread", required=True); r.add_argument("--tail", type=int, default=30)
    sub.add_parser("list")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    fn = {"create": cmd_create, "send": cmd_send, "inbox": cmd_inbox,
          "read": cmd_read, "list": cmd_list, "follow": cmd_follow}.get(a.cmd)
    if not fn:
        ap.print_help()
        return 1
    return fn(a)


if __name__ == "__main__":
    sys.exit(main())
