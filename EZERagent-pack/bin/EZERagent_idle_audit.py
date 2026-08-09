#!/usr/bin/env python3
"""상주 프로세스 위생 감사 — 유휴 claude CLI/node 프로세스 식별·보고 (SPEED_DESIGN_v3 D6).

식별·보고 전용이다. kill·정리 집행 기능은 절대 포함하지 않는다 — 정리는
CSO가 이 보고를 근거로 별도 수행한다. 이 도구는 어떤 프로세스도 종료하지 않는다.

판정 4조건(전부 충족해야 "정리 후보"):
  ① EZERagent 노드 레지스트리 미등록  — EZERagent list 등록 pid(부모 체인 포함)와 무관
  ② 라이브 surface 미매핑        — EZERagent status --json 라이브 surface에도 미매핑
  ③ CPU 임계 미만                — 기본 1.0% 미만
  ④ 경과시간 임계 초과            — 기본 6시간 (--idle-hours)
판정 불가·불명(레지스트리 조회 실패·etime 파싱 불가 등)이면 "보류(unknown)".
후보로 절대 올리지 않는다(살아있는 세션 오살상 방지가 최우선).

exit code는 항상 0 (보고 도구 — 게이트 아님).

사용:
  python3 EZERagent_idle_audit.py [--idle-hours 6] [--cpu-max 1.0] [--json]
  python3 EZERagent_idle_audit.py --self-test
"""
import argparse
import json
import os
import subprocess
import sys

EZERAGENT_TIMEOUT = 10          # 초 — EZERagent 서브프로세스 타임아웃
DEFAULT_IDLE_HOURS = 6.0  # 이 시간 초과 유휴만 후보 (④)
DEFAULT_CPU_MAX = 1.0     # 이 %CPU 미만만 후보 (③)
CLAUDE_VERSIONS_MARK = '.local/share/claude/versions/'


# ── ps 파싱 ─────────────────────────────────────────────────────────

def parse_ps_line(line):
    """`ps -axo pid,ppid,%cpu,etime,stat,tty,command` 한 줄을 dict로.

    파싱 불가(필드 부족·숫자 아님)면 None. 예외를 밖으로 던지지 않는다.
    """
    parts = line.split(None, 6)
    if len(parts) < 7:
        return None
    pid_s, ppid_s, cpu_s, etime_s, stat, tty, command = parts
    try:
        pid = int(pid_s)
        ppid = int(ppid_s)
        cpu = float(cpu_s)
    except ValueError:
        return None
    return {
        'pid': pid, 'ppid': ppid, 'cpu': cpu,
        'etime_raw': etime_s, 'etime_secs': parse_etime(etime_s),
        'stat': stat, 'tty': tty, 'command': command,
    }


def parse_etime(etime):
    """ps etime `[[dd-]hh:]mm:ss`를 초로. 파싱 불가면 None."""
    try:
        days = 0
        rest = etime
        if '-' in rest:
            d, rest = rest.split('-', 1)
            days = int(d)
        bits = [int(x) for x in rest.split(':')]
    except (ValueError, AttributeError):
        return None
    if len(bits) == 3:
        h, m, s = bits
    elif len(bits) == 2:
        h, m, s = 0, bits[0], bits[1]
    else:
        return None
    return days * 86400 + h * 3600 + m * 60 + s


def classify_kind(command):
    """대상 종류 판정: 'claude'(CLI)·'node'·None(비대상).

    데스크톱 앱(/Applications/Claude.app · ClaudeScience)은 CLI가 아니라 제외.
    """
    if not command:
        return None
    first = command.split()[0]
    base = os.path.basename(first)
    if CLAUDE_VERSIONS_MARK in command:
        return 'claude'
    if base == 'claude' or first.endswith('/claude'):
        return 'claude'
    if base == 'node' or first.endswith('/node'):
        return 'node'
    return None


def collect_procs():
    """전체 ps 스냅샷 파싱. (all_by_pid, targets) 반환.

    all_by_pid: {pid: proc} — 부모 체인 추적용 전체 프로세스.
    targets:    claude CLI·node 대상 proc 리스트.
    ps 실행 자체가 불가하면 ({}, []).
    """
    try:
        out = subprocess.run(
            ['ps', '-axo', 'pid,ppid,%cpu,etime,stat,tty,command'],
            capture_output=True, text=True, timeout=EZERAGENT_TIMEOUT,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}, []
    all_by_pid, targets = {}, []
    lines = out.splitlines()
    for ln in lines[1:] if lines else []:  # 헤더 1줄 제외
        proc = parse_ps_line(ln)
        if proc is None:
            continue
        all_by_pid[proc['pid']] = proc
        if classify_kind(proc['command']):
            targets.append(proc)
    return all_by_pid, targets


# ── EZERagent 레지스트리 조회 ─────────────────────────────────────────────

def _run_EZERagent(args):
    """EZERagent 서브커맨드 실행. (ok, stdout). 실패·부재면 (False, '')."""
    try:
        r = subprocess.run(['EZERagent'] + args, capture_output=True,
                           text=True, timeout=EZERAGENT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return False, ''
    if r.returncode != 0:
        return False, ''
    return True, r.stdout or ''


def parse_EZERagent_list(text):
    """`EZERagent list` 출력을 {pid: surface_ref}로. `pid=NNN`·`surface:NN` 파싱."""
    reg = {}
    for ln in text.splitlines():
        ref, pid = None, None
        for tok in ln.split():
            if tok.startswith('surface:') and ref is None:
                ref = tok
            elif tok.startswith('pid='):
                try:
                    pid = int(tok[4:])
                except ValueError:
                    pid = None
        if ref is not None and pid is not None:
            reg[pid] = ref
    return reg


def parse_EZERagent_status_refs(text):
    """`EZERagent status --json`에서 exited=false 라이브 surface_ref 집합. 실패면 None."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    refs = set()
    for s in data.get('surfaces', []):
        if s.get('exited') is False and s.get('surface_ref'):
            refs.add(s['surface_ref'])
    return refs


def load_registry():
    """EZERagent 레지스트리 로드.

    반환 dict:
      available   — EZERagent list 성공 여부(False면 ①②는 판정 불가)
      pid_to_ref  — {등록 pid: surface_ref}
      live_refs   — 라이브 surface_ref 집합 (status 실패 시 None)
    """
    ok, out = _run_EZERagent(['list'])
    pid_to_ref = parse_EZERagent_list(out) if ok else {}
    ok_st, out_st = _run_EZERagent(['status', '--json'])
    live_refs = parse_EZERagent_status_refs(out_st) if ok_st else None
    return {'available': ok, 'pid_to_ref': pid_to_ref, 'live_refs': live_refs}


# ── 부모 체인 추적 ──────────────────────────────────────────────────

def registered_ancestor(proc, all_by_pid, reg_pids):
    """proc의 pid·조상 pid 중 reg_pids에 든 첫 pid(등록 노드). 없으면 None."""
    seen = set()
    cur = proc['pid']
    while cur and cur not in seen:
        seen.add(cur)
        if cur in reg_pids:
            return cur
        node = all_by_pid.get(cur)
        if node is None or node['ppid'] == cur:
            break
        cur = node['ppid']
    return None


# ── 판정 ────────────────────────────────────────────────────────────

def judge(proc, all_by_pid, registry, idle_hours, cpu_max):
    """단일 대상 proc 판정. (verdict, conditions) 반환.

    verdict: 'candidate'|'active'|'unknown'
    conditions: 4조건 각각의 met(bool|None)·근거 문자열.
    """
    reg_pids = registry['pid_to_ref']
    live_refs = registry['live_refs']
    anc = registered_ancestor(proc, all_by_pid, reg_pids)

    if not registry['available']:
        # 레지스트리 조회 실패 → 등록 여부 판정 불가 → 보류
        c1 = {'met': None, 'why': 'EZERagent list 조회 실패 — 등록 여부 불명'}
        c2 = {'met': None, 'why': 'EZERagent 레지스트리 없음 — surface 매핑 불명'}
    else:
        c1 = {'met': anc is None,
              'why': ('등록 노드 무관(조상 미등록)' if anc is None
                      else f'등록 노드 pid {anc} ({reg_pids[anc]})에 매달림')}
        if anc is None:
            c2 = {'met': True, 'why': '라이브 surface 미매핑'}
        else:
            ref = reg_pids[anc]
            # status 성공 시 라이브 교차확인, 실패 시 EZERagent list를 라이브로 간주
            live = (ref in live_refs) if live_refs is not None else True
            c2 = {'met': not live,
                  'why': (f'라이브 surface {ref} 매핑' if live
                          else f'surface {ref} 미-라이브(등록만)')}

    et = proc['etime_secs']
    if et is None:
        c4 = {'met': None, 'why': f'etime 파싱 불가({proc["etime_raw"]})'}
    else:
        c4 = {'met': et > idle_hours * 3600,
              'why': f'경과 {fmt_dur(et)} ({">" if et > idle_hours*3600 else "<="} {idle_hours}h)'}

    c3 = {'met': proc['cpu'] < cpu_max,
          'why': f'CPU {proc["cpu"]:.1f}% ({"<" if proc["cpu"] < cpu_max else ">="} {cpu_max}%)'}

    conds = {'registry_unregistered': c1, 'surface_unmapped': c2,
             'cpu_below': c3, 'etime_over': c4}

    mets = [c['met'] for c in conds.values()]
    if None in mets:
        verdict = 'unknown'
    elif all(mets):
        verdict = 'candidate'
    else:
        verdict = 'active'
    return verdict, conds


def fmt_dur(secs):
    if secs is None:
        return '?'
    d, r = divmod(int(secs), 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    if d:
        return f'{d}d{h}h{m}m'
    if h:
        return f'{h}h{m}m'
    return f'{m}m'


def cmd_summary(command, width=70):
    c = ' '.join(command.split())
    return c if len(c) <= width else c[:width - 1] + '…'


def audit(idle_hours, cpu_max):
    """전체 감사 수행. 결과 dict 반환(순수 계산 — 출력 없음)."""
    all_by_pid, targets = collect_procs()
    registry = load_registry()
    rows = []
    for proc in targets:
        verdict, conds = judge(proc, all_by_pid, registry, idle_hours, cpu_max)
        rows.append({
            'pid': proc['pid'], 'ppid': proc['ppid'], 'kind': classify_kind(proc['command']),
            'cpu': proc['cpu'], 'etime': proc['etime_raw'], 'etime_secs': proc['etime_secs'],
            'tty': proc['tty'], 'command': cmd_summary(proc['command'], 200),
            'verdict': verdict, 'conditions': conds,
        })
    rows.sort(key=lambda r: (r['verdict'] != 'candidate', -(r['etime_secs'] or 0)))
    counts = {'candidate': 0, 'unknown': 0, 'active': 0}
    for r in rows:
        counts[r['verdict']] += 1
    return {
        'registry_available': registry['available'],
        'live_refs_available': registry['live_refs'] is not None,
        'idle_hours': idle_hours, 'cpu_max': cpu_max,
        'counts': counts, 'processes': rows,
    }


# ── 출력 ────────────────────────────────────────────────────────────

def render_text(result):
    out = []
    c = result['counts']
    out.append('■ 상주 프로세스 위생 감사 (식별·보고 전용 — kill 안 함)')
    out.append(f"  임계: 유휴 > {result['idle_hours']}h · CPU < {result['cpu_max']}%"
               f"  | EZERagent 레지스트리={'OK' if result['registry_available'] else '조회실패'}"
               f" · 라이브 surface={'OK' if result['live_refs_available'] else 'N/A'}")
    if not result['registry_available']:
        out.append('  ⚠ EZERagent list 조회 실패 → 등록 여부 판정 불가 → 전 대상 보류(unknown) 처리')
    out.append('')

    cands = [r for r in result['processes'] if r['verdict'] == 'candidate']
    holds = [r for r in result['processes'] if r['verdict'] == 'unknown']
    out.append(f'── 정리 후보 {len(cands)}개 (CSO 검토·집행 대상) ──')
    if not cands:
        out.append('  (없음)')
    for r in cands:
        out.append(f"  pid {r['pid']} [{r['kind']}] 경과 {fmt_dur(r['etime_secs'])}"
                   f" CPU {r['cpu']:.1f}% tty={r['tty']}")
        out.append(f"    cmd: {cmd_summary(r['command'])}")
        for key in ('registry_unregistered', 'surface_unmapped', 'cpu_below', 'etime_over'):
            cd = r['conditions'][key]
            out.append(f"    [{'✓' if cd['met'] else '·'}] {key}: {cd['why']}")

    out.append('')
    out.append(f'── 보류(unknown) {len(holds)}개 (판정 불가 — 절대 정리 금지) ──')
    if not holds:
        out.append('  (없음)')
    for r in holds:
        why = next((cd['why'] for cd in r['conditions'].values() if cd['met'] is None), '?')
        out.append(f"  pid {r['pid']} [{r['kind']}] 경과 {fmt_dur(r['etime_secs'])}"
                   f" CPU {r['cpu']:.1f}% — {why}")

    out.append('')
    out.append(f"idle-audit: 후보 {c['candidate']}개 · 보류 {c['unknown']}개 · 활성 {c['active']}개")
    return '\n'.join(out)


# ── self-test ───────────────────────────────────────────────────────

def self_test():
    """외부 프로세스 무의존 단위 테스트. 실패 시 AssertionError."""
    assert parse_etime('05') is None  # mm:ss 미만은 불가
    assert parse_etime('01:02') == 62
    assert parse_etime('01:02:03') == 3723
    assert parse_etime('2-03:04:05') == 2 * 86400 + 3 * 3600 + 4 * 60 + 5
    assert parse_etime('bad') is None

    assert classify_kind('/Users/x/.local/share/claude/versions/2.1.199 --agent-id a@b') == 'claude'
    assert classify_kind('claude --resume') == 'claude'
    assert classify_kind('/opt/homebrew/bin/node foo.js') == 'node'
    assert classify_kind('/Applications/Claude.app/Contents/Frameworks/Claude Helper --type=gpu') is None
    assert classify_kind('/Applications/Claude Science.app/Contents/MacOS/ClaudeScience') is None
    assert classify_kind('') is None

    p = parse_ps_line('  123   45   0.0    01-02:03:04 Ss+  ttys005  claude --agent-id x')
    assert p and p['pid'] == 123 and p['ppid'] == 45 and p['cpu'] == 0.0
    assert p['tty'] == 'ttys005' and p['command'] == 'claude --agent-id x'
    assert parse_ps_line('too few fields') is None

    reg = parse_EZERagent_list(
        'surface:393\trole=master\tpid=66798\texited=false\tsurface 393\t/wd\n'
        'surface:395\trole=worker\tpid=28438\texited=false\tworker\t/x')
    assert reg == {66798: 'surface:393', 28438: 'surface:395'}

    live = parse_EZERagent_status_refs(json.dumps({'surfaces': [
        {'surface_ref': 'surface:393', 'exited': False},
        {'surface_ref': 'surface:999', 'exited': True}]}))
    assert live == {'surface:393'}
    assert parse_EZERagent_status_refs('not json') is None

    # 조상 추적: 자식(child)이 등록 노드(worker)에 매달림 → 등록
    all_by_pid = {
        28438: {'pid': 28438, 'ppid': 1, 'command': 'worker'},
        50000: {'pid': 50000, 'ppid': 28438, 'command': 'child'},
        30675: {'pid': 30675, 'ppid': 1, 'command': 'tmux'},
        90000: {'pid': 90000, 'ppid': 30675, 'command': 'orphan'},
    }
    reg_pids = {66798: 'surface:393', 28438: 'surface:395'}
    assert registered_ancestor(all_by_pid[50000], all_by_pid, reg_pids) == 28438
    assert registered_ancestor(all_by_pid[90000], all_by_pid, reg_pids) is None

    registry = {'available': True, 'pid_to_ref': reg_pids, 'live_refs': {'surface:393', 'surface:395'}}

    # ① 등록 노드 자식 → active (등록됨)
    child = {'pid': 50000, 'ppid': 28438, 'cpu': 0.0, 'etime_secs': 99999,
             'etime_raw': '1-00:00:00', 'tty': '??', 'command': 'node child'}
    v, _ = judge(child, all_by_pid, registry, DEFAULT_IDLE_HOURS, DEFAULT_CPU_MAX)
    assert v == 'active', v

    # ② 미등록·유휴·저CPU·노후 고아 → candidate
    orphan = {'pid': 90000, 'ppid': 30675, 'cpu': 0.1, 'etime_secs': 100000,
              'etime_raw': '1-03:46:40', 'tty': 'ttys012', 'command': 'claude --agent-id x@y'}
    v, cds = judge(orphan, all_by_pid, registry, DEFAULT_IDLE_HOURS, DEFAULT_CPU_MAX)
    assert v == 'candidate', (v, cds)

    # ③ 미등록이나 CPU 높음 → active(후보 아님)
    busy = dict(orphan, cpu=42.0)
    v, _ = judge(busy, all_by_pid, registry, DEFAULT_IDLE_HOURS, DEFAULT_CPU_MAX)
    assert v == 'active', v

    # ④ 미등록·저CPU이나 신생(경과 짧음) → active
    fresh = dict(orphan, etime_secs=60, etime_raw='01:00')
    v, _ = judge(fresh, all_by_pid, registry, DEFAULT_IDLE_HOURS, DEFAULT_CPU_MAX)
    assert v == 'active', v

    # etime 파싱 불가 → unknown
    noet = dict(orphan, etime_secs=None, etime_raw='bad')
    v, _ = judge(noet, all_by_pid, registry, DEFAULT_IDLE_HOURS, DEFAULT_CPU_MAX)
    assert v == 'unknown', v

    # 레지스트리 조회 실패 → unknown (오살상 방지)
    reg_down = {'available': False, 'pid_to_ref': {}, 'live_refs': None}
    v, _ = judge(orphan, all_by_pid, reg_down, DEFAULT_IDLE_HOURS, DEFAULT_CPU_MAX)
    assert v == 'unknown', v

    print('self-test: PASS (15 groups)')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='유휴 claude CLI/node 프로세스 식별·보고 (kill 안 함 — 정리는 CSO).')
    ap.add_argument('--idle-hours', type=float, default=DEFAULT_IDLE_HOURS,
                    help=f'유휴 임계 시간(기본 {DEFAULT_IDLE_HOURS}h)')
    ap.add_argument('--cpu-max', type=float, default=DEFAULT_CPU_MAX,
                    help=f'후보 CPU 상한%% 미만(기본 {DEFAULT_CPU_MAX})')
    ap.add_argument('--json', action='store_true', help='JSON 출력')
    ap.add_argument('--self-test', action='store_true', help='단위 테스트(외부 무의존)')
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    result = audit(args.idle_hours, args.cpu_max)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_text(result))
    return 0  # 항상 0 — 보고 도구


if __name__ == '__main__':
    sys.exit(main())
