#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EZERagent_reflect — 반복신호 light scan (자기교정 ① Capture 자동화).

외부 /reflect shadow mode의 EZERagent판. Stop·SessionEnd hook이 세션 transcript를
1회 가볍게 훑어, 사람(오너)이 master를 교정·반려한 '마찰 신호'를 카운트한다.
한 세션(transcript)에서 임계(기본 3) 이상 누적되면 RSI_LEDGER.md(① Capture)에
SHADOW 후보 1줄을 append 한다 — 자동 적용은 0(shadow). 적재된 후보는
inject-context.sh가 startup/resume에 RSI 자산으로 주입하므로 master 눈에 들어와
검토된다(reflect=write ↔ inject-context=read 의 폐회로).

설계: _round/RSI_PROTOCOL.md ① Capture · 외부 메모리 아키텍처 접목평가 항목①·③.
shadow 안전: ledger append만. 채점·자동수정·자동승격 일절 없음(producer≠evaluator).
정밀도: 마찰 어휘는 '교정/반려'에 강하게 치우친 보수적 셋. shadow라 false positive는
        master 검토에서 걸러지므로 recall보다 무해성을 우선한다.

사용:
    python3 EZERagent_reflect.py scan --transcript <path.jsonl> --ledger <RSI_LEDGER.md> \
        [--threshold 3] [--json]      # 1회 스캔 (hook이 호출)
    python3 EZERagent_reflect.py --self-test                  # 결정론 자기검증 (preflight C28)

공통: --transcript 없거나 못 읽으면 조용히 0 (hook이 세션을 깨지 않게).

종료 코드: 0 정상(적재 여부 무관) · 1 self-test 실패 · 2 인자/입력 오류
의존성: 파이썬 표준 라이브러리만 (네트워크·LLM 호출 없음).
"""

import argparse
import json
import os
import re
import sys
import tempfile

# 마찰(교정·반려) 신호 — 사람이 master의 산출/행동을 부정·되돌리는 표현에 치우친 보수적 셋.
# 일반 작업지시("에러 고쳐줘")와 겹치는 약한 어휘('오류'·'실패'·'again' 단독)는 의도적으로 제외.
FRICTION_PATTERNS = [
    "틀렸", "틀린", "잘못됐", "잘못 됐", "잘못했", "잘못 했", "잘못 하",
    "그게 아니", "그건 아니", "그렇게 아니", "아니라고", "아니야", "아니잖",
    "다시 해", "다시 하", "다시 해라", "되돌려", "원래대로", "왜 안 ", "왜 못",
    "하지 마", "하지마", "또 그", "또 틀", "말했잖", "시켰잖", "몇 번",
    "that's wrong", "that is wrong", "you're wrong", "that's not", "that is not",
    "not what i", "incorrect", "undo that", "revert that", "stop doing", "still not",
    "still broken", "still failing", "wrong again",
]

# 시스템/하네스가 끼워넣은 user 줄(로컬 커맨드·caveat·reminder)은 사람 입력이 아니다 → 스캔 제외.
# launch-agent/hook이 stdin push로 주입하는 디렉티브 블록도 user role로 기록되므로 같은 부류다
# (선두 헤더 prefix만 매칭 — 디렉티브를 '인용'하는 진짜 사람 발화는 계속 잡힌다).
SYSTEM_PREFIXES = ("<command-", "<local-command", "Caveat:", "<system-reminder",
                   "■ EZERagent", "# MASTER ABSOLUTE DIRECTIVE", "# WORKER ABSOLUTE DIRECTIVE",
                   "# CSO ABSOLUTE DIRECTIVE", "# REVIEWER ABSOLUTE DIRECTIVE",
                   "# CEO (master of master)", "# RSI 학습 루프")


def iter_human_messages(transcript_path):
    """transcript JSONL에서 '사람이 직접 친' user 메시지 텍스트만 순서대로 yield.

    - type=='user' AND message.role=='user' AND content가 str (tool_result=list는 제외)
    - 시스템 주입 user 줄(command/caveat/reminder)은 제외
    - 깨진 줄은 조용히 건너뜀
    """
    try:
        f = open(transcript_path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "user":
                continue
            msg = d.get("message")
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue  # list content = tool_result 등 비-사람입력
            text = content.strip()
            if not text or text.startswith(SYSTEM_PREFIXES):
                continue
            yield text, d.get("timestamp", "")


def session_id_of(transcript_path):
    """transcript에서 sessionId 추출 (첫 발견값). 없으면 파일명 stem."""
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    sid = json.loads(line).get("sessionId")
                except ValueError:
                    continue
                if sid:
                    return sid
    except OSError:
        pass
    return os.path.splitext(os.path.basename(transcript_path))[0]


def detect_friction(text):
    """메시지에서 매칭된 마찰 어휘 집합 (대소문자 무시). 비면 마찰 없음."""
    low = text.lower()
    hits = set()
    for pat in FRICTION_PATTERNS:
        if pat in text or pat.lower() in low:
            hits.add(pat)
    return hits


def already_logged(ledger_path, sid):
    """이 세션이 ledger에 이미 reflect:auto 후보로 적재됐나 (멱등 가드).
    sid 전체로 비교 — 파일명 fallback의 짧은 prefix 충돌을 방지한다."""
    if not os.path.isfile(ledger_path):
        return False
    try:
        text = open(ledger_path, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    return ("reflect:auto" in text) and (("session %s" % sid) in text)


def scan(transcript_path, ledger_path, threshold):
    """transcript 1회 스캔 → 임계 이상이면 ledger에 SHADOW 후보 1줄 append.

    반환: 결과 dict (출력·self-test 공용).
    """
    result = {"scanned": 0, "friction": 0, "threshold": threshold,
              "appended": False, "session": None, "signals": [], "reason": ""}
    if not transcript_path or not os.path.isfile(transcript_path):
        result["reason"] = "transcript 없음"
        return result

    sid = session_id_of(transcript_path)
    result["session"] = sid

    scanned = 0
    friction_msgs = 0
    all_signals = set()
    first_evidence = ""
    last_ts = ""
    for text, ts in iter_human_messages(transcript_path):
        scanned += 1
        if ts:
            last_ts = ts
        hits = detect_friction(text)
        if hits:
            friction_msgs += 1
            all_signals |= hits
            if not first_evidence:
                first_evidence = re.sub(r"\s+", " ", text)[:80]
    result["scanned"] = scanned
    result["friction"] = friction_msgs
    result["signals"] = sorted(all_signals)

    if friction_msgs < threshold:
        result["reason"] = "임계 미달 (%d<%d)" % (friction_msgs, threshold)
        return result
    if already_logged(ledger_path, sid):
        result["reason"] = "이미 적재된 세션 (멱등)"
        return result

    # ── SHADOW 후보 1줄 append (자동적용 0 — 사람 검토용) ──
    date = (last_ts or "")[:10]
    sig_str = ", ".join(sorted(all_signals)[:8])
    line = ("- [reflect:auto SHADOW] %s session %s 마찰신호 %d건 — 반복 결함 후보"
            "(자동적용0·사람검토). 신호: %s. 근거 예: \"%s\"\n"
            % (date, sid, friction_msgs, sig_str, first_evidence))
    try:
        os.makedirs(os.path.dirname(ledger_path) or ".", exist_ok=True)
        prev = ""
        if os.path.isfile(ledger_path):
            prev = open(ledger_path, encoding="utf-8", errors="replace").read()
        with open(ledger_path, "a", encoding="utf-8") as f:
            if prev and not prev.endswith("\n"):
                f.write("\n")
            f.write(line)
        result["appended"] = True
        result["reason"] = "후보 적재"
    except OSError as e:
        result["reason"] = "ledger 쓰기 실패: %s" % e
    return result


def cmd_scan(args):
    res = scan(args.transcript, args.ledger, args.threshold)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print("reflect scan: 사람메시지 %d · 마찰 %d/%d · 적재=%s (%s)"
              % (res["scanned"], res["friction"], res["threshold"],
                 res["appended"], res["reason"]))
    return 0  # 항상 0 — hook이 세션을 깨지 않게


def self_test():
    """tempdir 라운드트립 — 임계초과→적재, 멱등(중복 안 함), 임계미달→무적재,
    tool_result(list)·시스템 user 줄 제외, 깨진 줄 무시 까지 검증."""
    failures = []
    with tempfile.TemporaryDirectory(prefix="EZERagent-reflect-selftest-") as td:
        tpath = os.path.join(td, "t.jsonl")
        ledger = os.path.join(td, "RSI_LEDGER.md")

        def urow(content):
            return json.dumps({"type": "user", "sessionId": "abcd1234efgh",
                               "timestamp": "2026-06-13T10:00:00Z",
                               "message": {"role": "user", "content": content}})

        lines = [
            urow("이거 틀렸어, 다시 해줘"),            # 마찰 2어휘
            urow("그게 아니라 다른 방식으로"),          # 마찰
            json.dumps({"type": "assistant", "message": {"role": "assistant",
                        "content": [{"type": "text", "text": "네"}]}}),
            urow("왜 안 되는거야"),                    # 마찰
            # tool_result(list content)는 사람입력 아님 → 제외돼야
            json.dumps({"type": "user", "sessionId": "abcd1234efgh",
                        "message": {"role": "user",
                                    "content": [{"type": "tool_result", "content": "틀렸"}]}}),
            urow("<command-name>/foo</command-name> 틀렸"),  # 시스템 주입 → 제외
            "{깨진 줄",                                # 깨진 줄 → 무시
            urow("정상적인 작업 지시입니다"),          # 마찰 아님
        ]
        open(tpath, "w", encoding="utf-8").write("\n".join(lines) + "\n")

        # 1) 임계(3) 도달 → 적재
        r1 = scan(tpath, ledger, 3)
        if r1["friction"] != 3:
            failures.append("마찰 카운트 오류: %d (기대 3) signals=%s" % (r1["friction"], r1["signals"]))
        if not r1["appended"]:
            failures.append("임계 도달인데 미적재: %s" % r1["reason"])
        if not os.path.isfile(ledger) or "reflect:auto" not in open(ledger, encoding="utf-8").read():
            failures.append("ledger에 reflect:auto 후보가 안 보임")

        # 2) 멱등 — 재실행은 중복 적재 안 함
        before = open(ledger, encoding="utf-8").read()
        r2 = scan(tpath, ledger, 3)
        after = open(ledger, encoding="utf-8").read()
        if r2["appended"] or before != after:
            failures.append("멱등 위반: 같은 세션 재적재됨")

        # 3) 임계 미달 → 무적재 (새 세션·빈 ledger)
        tpath2 = os.path.join(td, "t2.jsonl")
        ledger2 = os.path.join(td, "L2.md")
        open(tpath2, "w", encoding="utf-8").write(
            urow("틀렸어") + "\n" + urow("정상 지시") + "\n")
        # sessionId가 같으면 멱등에 걸리니 다른 세션으로
        open(tpath2, "w", encoding="utf-8").write(
            json.dumps({"type": "user", "sessionId": "zzzz9999",
                        "timestamp": "2026-06-13T11:00:00Z",
                        "message": {"role": "user", "content": "틀렸어"}}) + "\n")
        r3 = scan(tpath2, ledger2, 3)
        if r3["appended"]:
            failures.append("임계 미달인데 적재됨")
        if os.path.isfile(ledger2):
            failures.append("미달인데 ledger 파일 생성됨")

        # 4) transcript 없음 → 조용히 무적재, exit 0 경로
        r4 = scan(os.path.join(td, "nope.jsonl"), ledger2, 3)
        if r4["appended"] or r4["reason"] != "transcript 없음":
            failures.append("transcript 부재 처리 오류: %s" % r4["reason"])

        # 5) 디렉티브 stdin-push 주입(선두 헤더)은 마찰 미집계,
        #    디렉티브를 '인용'하는 진짜 사람 발화는 계속 집계돼야 한다.
        tpath3 = os.path.join(td, "t3.jsonl")
        ledger3 = os.path.join(td, "L3.md")

        def urow3(content):
            return json.dumps({"type": "user", "sessionId": "dirtest01",
                               "timestamp": "2026-06-13T12:00:00Z",
                               "message": {"role": "user", "content": content}})

        open(tpath3, "w", encoding="utf-8").write("\n".join([
            urow3("# WORKER ABSOLUTE DIRECTIVE — 워커 절대지침\n하지 마 · 되돌려 · 틀린 것 금지"),
            urow3("■ EZERagent 역할 각성 (EZERAGENT_ROLE=worker)\n하지 마 시켰잖"),
            urow3("WORKER_DIRECTIVE에 하지 마라고 했는데 왜 안 지켜"),  # 인용 사람발화 → 마찰
            urow3("또 틀렸어 되돌려"),                                  # 마찰
            urow3("몇 번을 말했잖아"),                                  # 마찰
        ]) + "\n")
        r5 = scan(tpath3, ledger3, 3)
        if r5["friction"] != 3:
            failures.append("디렉티브 주입 오탐: friction=%d (기대 3) signals=%s"
                            % (r5["friction"], r5["signals"]))
        if not r5["appended"]:
            failures.append("디렉티브 필터가 진짜 마찰까지 억제: %s" % r5["reason"])

    print(json.dumps({"self_test": "ok" if not failures else "fail",
                      "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(description="반복신호 light scan (자기교정 Capture)")
    ap.add_argument("--self-test", action="store_true", help="결정론 자기검증")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("scan", help="transcript 1회 스캔 → 임계 이상이면 ledger 후보 적재")
    s.add_argument("--transcript", required=True, help="세션 transcript JSONL 경로")
    s.add_argument("--ledger", required=True, help="RSI_LEDGER.md 경로 (적재 대상)")
    s.add_argument("--threshold", type=int, default=3, help="마찰 메시지 임계 (기본 3)")
    s.add_argument("--json", action="store_true")

    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.cmd == "scan":
        return cmd_scan(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
