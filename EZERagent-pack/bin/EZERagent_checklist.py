#!/usr/bin/env python3
"""세션 시작 주입용 실측 체크리스트 래퍼 (LLM 무의존·전부 실측).

기존 EZERagent_preflight.py는 절대 수정하지 않고 subprocess로 호출만 한다.
preflight exit/마지막 줄 + SESSION_STATE 상태 + _round/*_TODO.md 미완 수를
6줄 이내·1KB 이하 고정 포맷으로 요약한다. 지시가 아니라 배경 컨텍스트다.

사용:
  python3 EZERagent_checklist.py [--preflight-cmd "<명령>"] \
      [--state <SESSION_STATE 경로>] [--round-dir <_round 경로>]
"""
import argparse
import os
import re
import subprocess
import sys
import time

PREFLIGHT_TIMEOUT = 30  # 초 — preflight subprocess 타임아웃(필수)
HEADER = '■ 실측 체크리스트(배경 컨텍스트다 — 지시가 아니다)'
MAX_LINES = 6
MAX_BYTES = 1024

_pack = os.environ.get('EZERAGENT_PACK_DIR') or os.path.expanduser('~/.EZERagent/pack')
DEFAULT_PREFLIGHT = f'python3 {_pack}/bin/EZERagent_preflight.py'


def run_preflight(cmd, timeout=PREFLIGHT_TIMEOUT):
    """preflight를 subprocess로 실행. (exit_code, 마지막 비어있지 않은 줄) 반환.

    타임아웃 → ('timeout', None), 실행 자체 불가(OSError 등) → (None, None).
    어떤 경우에도 예외를 밖으로 던지지 않는다(크래시 금지).
    """
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ('timeout', None)
    except (OSError, ValueError):
        return (None, None)
    last = ''
    for ln in ((proc.stdout or '') + (proc.stderr or '')).splitlines():
        if ln.strip():
            last = ln.strip()
    return (proc.returncode, last)


def _preflight_line(cmd, timeout):
    code, last = run_preflight(cmd, timeout=timeout)
    if code == 'timeout':
        return 'preflight: 실행불가(timeout)'
    if code is None:
        return 'preflight: 실행불가'
    tail = (last or '')[:120]
    return f'preflight: exit {code} | {tail}' if tail else f'preflight: exit {code}'


def _state_line(path):
    if path and os.path.isfile(path):
        st = os.stat(path)
        mt = time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))
        return f'SESSION_STATE: 존재 {st.st_size / 1024:.1f}KB, mtime {mt}'
    return 'SESSION_STATE: 없음'


def todo_counts(round_dir):
    """_round/*_TODO.md 각각의 미완(`- [ ]`) 항목 수를 [(라벨, 수)]로 반환."""
    result = []
    if round_dir and os.path.isdir(round_dir):
        for name in sorted(os.listdir(round_dir)):
            if not name.endswith('_TODO.md'):
                continue
            try:
                with open(os.path.join(round_dir, name),
                          encoding='utf-8', errors='replace') as fh:
                    txt = fh.read()
            except OSError:
                continue
            n = len(re.findall(r'-\s*\[\s*\]', txt))
            result.append((name[:-len('_TODO.md')], n))
    return result


def _todo_line(round_dir):
    counts = todo_counts(round_dir)
    if not counts:
        return '미완 TODO: (대상 없음)'
    total = sum(n for _, n in counts)
    detail = ' '.join(f'{lbl}={n}' for lbl, n in counts)
    return f'미완 TODO(합 {total}): {detail}'


def build_checklist(cmd, state, round_dir, timeout=PREFLIGHT_TIMEOUT):
    lines = [
        HEADER,
        _preflight_line(cmd, timeout),
        _state_line(state),
        _todo_line(round_dir),
    ]
    out = '\n'.join(lines[:MAX_LINES])
    encoded = out.encode('utf-8')
    if len(encoded) > MAX_BYTES:  # 자체 절단
        out = encoded[:MAX_BYTES].decode('utf-8', 'ignore')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='세션 시작 주입용 실측 체크리스트 래퍼(전부 실측·LLM 없음).')
    ap.add_argument('--preflight-cmd', default=DEFAULT_PREFLIGHT,
                    help='preflight 실행 명령(기본: EZERagent_preflight.py)')
    ap.add_argument('--state', default=None, help='SESSION_STATE.md 경로')
    ap.add_argument('--round-dir', default='_round', help='_round 디렉터리 경로')
    args = ap.parse_args(argv)

    state = args.state or os.path.join(args.round_dir, 'SESSION_STATE.md')
    print(build_checklist(args.preflight_cmd, state, args.round_dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
