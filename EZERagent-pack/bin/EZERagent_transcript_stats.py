#!/usr/bin/env python3
"""EZERagent_transcript_stats — 세션 전사(JSONL)에서 결정론 노력·검증 통계 추출.

출처: Steinberger 강연(2026-06-25 SF) agent-transcript 스킬 증류 —
"전사가 길수록 그 사람이 실제로 이해하려 했다는 신뢰가 올라간다"를
EZERagent 철학(환각0·산문 신고 대신 결정론 수치)으로 포트.
OpenClaw는 전사 '본문'을 redaction 후 첨부하지만, 우리는 '통계만' 추출한다
— 본문 미노출 = sanitize 실패 리스크 자체가 없다(fail-closed by design).

사용:
  python3 EZERagent_transcript_stats.py --latest            # 이 프로젝트 최신 세션
  python3 EZERagent_transcript_stats.py --session <path>    # 특정 JSONL
  python3 EZERagent_transcript_stats.py --latest --oneline  # evidence 한 줄용

evidence 접합:
  EZERagent_task.py set-status <id> done --evidence "$(... --latest --oneline)"

exit: 0=성공 · 2=세션 파일 없음 · 3=파싱 실패(유효 이벤트 0)
"""
import argparse
import glob
import json
import os
import re
import sys

TEST_CMD_RE = re.compile(
    r"\b(pytest|unittest|npm (run )?test|yarn test|cargo (test|check)|go test"
    r"|bun test|jest|vitest|node --check|python3? -m (pytest|unittest)"
    r"|preflight|EZERagent_.*eval|validate)\b"
)


# 주: 팩 기준선은 Python 3.9 호환(stock macOS python3) — PEP604(`X | None`) 주석 금지.
def find_latest(project_dir):
    files = glob.glob(os.path.join(project_dir, "*.jsonl"))
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def derive_project_dirs(cwd=None, home=None):
    """CWD → 세션 디렉토리 후보 유도(개인 경로 하드코딩 금지 — pack scan gate·v0.12.4 교훈).

    슬러그 규약: 절대경로의 '/'와 '.'을 '-'로 치환(예: /Users/x/P → -Users-x-P).
    프로필(~/.claude*)이 복수이므로 전부 스캔해 존재하는 후보를 반환. 순수 함수(테스트 주입 가능).
    """
    cwd = cwd or os.getcwd()
    home = home or os.path.expanduser("~")
    slug = cwd.replace("/", "-").replace(".", "-")
    out = []
    for prof in sorted(glob.glob(os.path.join(home, ".claude*"))):
        d = os.path.join(prof, "projects", slug)
        if os.path.isdir(d):
            out.append(d)
    return out


def resolve_project_dir(explicit=None):
    """유도 순서: ①명시 인자 ②env EZERAGENT_SESSION_PROJECT_DIR ③CWD 슬러그(최신 세션 보유 프로필).
    실패 시 None — 호출부가 exit 2(연성 의존 계약: 배선부는 이를 '통계 생략'으로 처리)."""
    if explicit:
        return explicit
    env = os.environ.get("EZERAGENT_SESSION_PROJECT_DIR")
    if env:
        return env
    cands = derive_project_dirs()
    if not cands:
        return None
    # 프로필 복수면 최신 세션(jsonl mtime)을 가진 쪽 — 결정론
    def newest(d):
        f = find_latest(d)
        return os.path.getmtime(f) if f else 0.0
    return max(cands, key=newest)


def collect(path):
    stats = {
        "session": os.path.basename(path).replace(".jsonl", ""),
        "user_turns": 0,
        "assistant_turns": 0,
        "tool_calls": {},
        "files_touched": set(),
        "bash_commands": 0,
        "test_like_commands": 0,
        "first_ts": None,
        "last_ts": None,
        "events": 0,
    }
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            stats["events"] += 1
            ts = d.get("timestamp")
            if ts:
                if stats["first_ts"] is None:
                    stats["first_ts"] = ts
                stats["last_ts"] = ts
            t = d.get("type")
            msg = d.get("message")
            if t == "user" and isinstance(msg, dict):
                c = msg.get("content")
                # tool_result만 담긴 user 이벤트는 사람 턴이 아니다
                if isinstance(c, str) or (
                    isinstance(c, list)
                    and any(
                        isinstance(b, dict) and b.get("type") == "text" for b in c
                    )
                ):
                    stats["user_turns"] += 1
            elif t == "assistant" and isinstance(msg, dict):
                stats["assistant_turns"] += 1
                c = msg.get("content")
                if isinstance(c, list):
                    for b in c:
                        if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                            continue
                        name = b.get("name") or "?"
                        stats["tool_calls"][name] = stats["tool_calls"].get(name, 0) + 1
                        inp = b.get("input") or {}
                        if name in ("Edit", "Write", "NotebookEdit"):
                            fp = inp.get("file_path")
                            if fp:
                                stats["files_touched"].add(fp)
                        elif name == "Bash":
                            stats["bash_commands"] += 1
                            cmd = inp.get("command") or ""
                            if TEST_CMD_RE.search(cmd):
                                stats["test_like_commands"] += 1
    return stats


def duration_min(stats):
    if not (stats["first_ts"] and stats["last_ts"]):
        return None
    try:
        from datetime import datetime

        fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
        a = datetime.strptime(stats["first_ts"], fmt)
        b = datetime.strptime(stats["last_ts"], fmt)
        return round((b - a).total_seconds() / 60, 1)
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="세션 JSONL 경로")
    ap.add_argument("--latest", action="store_true", help="프로젝트 최신 세션 사용")
    ap.add_argument(
        "--project-dir", default=None,
        help="세션 JSONL 디렉토리(생략 시 env EZERAGENT_SESSION_PROJECT_DIR → CWD 슬러그 유도)",
    )
    ap.add_argument("--oneline", action="store_true", help="evidence 한 줄 출력")
    args = ap.parse_args()

    path = args.session
    if not path and args.latest:
        pdir = resolve_project_dir(args.project_dir)
        if pdir:
            path = find_latest(pdir)
    if not path or not os.path.isfile(path):
        print("ERROR: 세션 JSONL 없음", file=sys.stderr)
        return 2

    s = collect(path)
    if s["events"] == 0:
        print("ERROR: 유효 이벤트 0 (파싱 실패)", file=sys.stderr)
        return 3

    dur = duration_min(s)
    edits = sum(s["tool_calls"].get(k, 0) for k in ("Edit", "Write", "NotebookEdit"))
    if args.oneline:
        print(
            f"transcript-stats[{s['session'][:8]}]: "
            f"{dur if dur is not None else '?'}min "
            f"user={s['user_turns']} asst={s['assistant_turns']} "
            f"edits={edits} files={len(s['files_touched'])} "
            f"bash={s['bash_commands']} tests={s['test_like_commands']}"
        )
    else:
        out = dict(s)
        out["files_touched"] = sorted(out["files_touched"])
        out["duration_min"] = dur
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
