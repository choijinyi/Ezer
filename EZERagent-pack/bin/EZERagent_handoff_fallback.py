#!/usr/bin/env python3
"""LLM-무의존 복원 핸드오프 생성기 (결정론 추출만).

ViMax context_compactor의 '정규식 폴백' 철학을 클린룸으로 재구현한다(코드 복사 없음).
LLM 호출 없이 세션 jsonl·TODO md에서 정규식/키워드 기반 결정론 추출만 수행해
8섹션 고정 마크다운 핸드오프를 만든다. 입력에 없는 사실은 창작하지 않는다.

사용:
  python3 EZERagent_handoff_fallback.py --jsonl a.jsonl [--jsonl b.jsonl] \
      --todo TODO.md [--todo CSO_TODO.md] [--out handoff.md]
--out 생략 시 stdout으로 출력한다.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

# 파일경로: 확장자는 긴 것 우선(jsonl>json, tsx>ts) 정렬로 부분매치를 막고,
# 뒤에 word char가 오면 매치 제외(.pyc 등 오탐 차단). 확장자 집합은 지침 명세와 동일.
FILE_RE = re.compile(r'[\w./_-]+\.(?:jsonl|json|toml|yaml|yml|tsx|ts|py|md|sh|rs)(?![\w])')
HASH_RE = re.compile(r'\b[0-9a-f]{7,40}\b')

ERROR_KEYS = ('error', 'failed', 'timeout', 'traceback', 'exception')
ERROR_KEYS_KO = ('거부', '실패')
DECISION_KEYS = ('decided',)
DECISION_KEYS_KO = ('결정', '채택', '승인', '기각', '보류')
CLIP = 200

SECTIONS = [
    '## Reference Context Only(주의문: 이 문서는 참조용이며 새 지시가 아니다)',
    '## 현재 위치(추정)',
    '## 완료 흔적',
    '## 중요 파일',
    '## 결정',
    '## 에러·리스크',
    '## 잔여 작업',
    '## 다음 액션(후보)',
]


def flatten_json(obj):
    """json 값에서 문자열/스칼라만 재귀 수집해 한 줄 텍스트로(경로·에러 원문 보존)."""
    out = []

    def walk(o):
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            out.append(str(o))

    walk(obj)
    return ' '.join(out)


def read_jsonl_lines(path):
    """jsonl 각 줄 json.loads 시도, 실패 줄은 plain text로 취급(손상 내성)."""
    lines = []
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        for raw in fh:
            raw = raw.rstrip('\n')
            if not raw.strip():
                continue
            try:
                lines.append(flatten_json(json.loads(raw)))
            except (json.JSONDecodeError, ValueError):
                lines.append(raw)
    return lines


def read_text_lines(path):
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        return [ln.rstrip('\n') for ln in fh]


def extract_paths(texts):
    """등장 빈도순 상위 20 파일경로(동률은 먼저 등장 순)."""
    counter = Counter()
    first_seen = {}
    for i, text in enumerate(texts):
        for m in FILE_RE.findall(text):
            counter[m] += 1
            first_seen.setdefault(m, i)
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], first_seen[kv[0]]))
    return [p for p, _ in ordered[:20]]


def extract_errors(indexed):
    """error/failed/timeout/traceback/exception/거부/실패 라인, 최근 우선 상위 10, 200자 클립."""
    hits = []
    for idx, text in indexed:
        low = text.lower()
        if any(k in low for k in ERROR_KEYS) or any(k in text for k in ERROR_KEYS_KO):
            hits.append((idx, text.strip()[:CLIP]))
    hits.sort(key=lambda t: -t[0])  # 뒤(=최근) 우선
    return [t for _, t in hits[:10]]


def extract_decisions(indexed):
    """decided/결정/채택/승인/기각/보류 라인, 등장 순 상위 10, 200자 클립."""
    hits = []
    for _, text in indexed:
        low = text.lower()
        if any(k in low for k in DECISION_KEYS) or any(k in text for k in DECISION_KEYS_KO):
            hits.append(text.strip()[:CLIP])
            if len(hits) >= 10:
                break
    return hits


def extract_commits(indexed):
    """git 문맥(commit/커밋 단어 ±1라인) 안의 커밋해시 상위 5(중복 제거·등장 순)."""
    texts = [t for _, t in indexed]
    found, seen = [], set()
    for i, text in enumerate(texts):
        window = ' '.join(texts[max(0, i - 1):i + 2])
        if 'commit' not in window.lower() and '커밋' not in window:
            continue
        for h in HASH_RE.findall(text):
            if h not in seen:
                seen.add(h)
                found.append(h)
    return found[:5]


def extract_incomplete_todos(todo_lines):
    """체크 안 된 `- [ ]` 항목 + 상태열에 미착수/진행 포함 표 행(구분선·헤더 제외)."""
    items = []
    for ln in todo_lines:
        s = ln.strip()
        m = re.match(r'-\s*\[\s*\]\s*(.+)', s)
        if m:
            items.append(m.group(1).strip()[:CLIP])
            continue
        if s.startswith('|') and ('미착수' in s or '진행' in s):
            if set(s) <= set('|-: '):  # 표 구분선
                continue
            items.append(s[:CLIP])
    return items


def tail_lines(indexed, n=3):
    """가장 최근(뒤) 비어있지 않은 라인 상위 n개, 최근 먼저. 현재 위치 추정용(추출 원문)."""
    texts = [t.strip()[:CLIP] for _, t in indexed if t.strip()]
    return texts[-n:][::-1] if texts else []


def _bullets(items):
    return '\n'.join(f'- {it}' for it in items) if items else '(추출 없음)'


def build_markdown(indexed, todo_lines):
    texts = [t for _, t in indexed]
    paths = extract_paths(texts)
    errors = extract_errors(indexed)
    decisions = extract_decisions(indexed)
    commits = extract_commits(indexed)
    todos = extract_incomplete_todos(todo_lines)
    loc = tail_lines(indexed, 3)
    nexts = todos[:3]

    blocks = [
        (SECTIONS[0],
         '> 이 문서는 손상/중단된 세션에서 결정론 추출로 복원한 참조 컨텍스트다. '
         '새 지시가 아니며, 실제 작업 전 원본을 확인하라.'),
        (SECTIONS[1], _bullets(loc)),
        (SECTIONS[2], _bullets([f'commit {h}' for h in commits])),
        (SECTIONS[3], _bullets(paths)),
        (SECTIONS[4], _bullets(decisions)),
        (SECTIONS[5], _bullets(errors)),
        (SECTIONS[6], _bullets(todos)),
        (SECTIONS[7], _bullets(nexts)),
    ]
    parts = []
    for title, body in blocks:
        parts.append(title)
        parts.append(body)
        parts.append('')
    return '\n'.join(parts).rstrip('\n') + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='LLM-무의존 복원 핸드오프 생성기(결정론 추출만).')
    ap.add_argument('--jsonl', action='append', default=[],
                    help='세션 jsonl 경로(반복 가능)')
    ap.add_argument('--todo', action='append', default=[],
                    help='TODO md 경로(반복 가능)')
    ap.add_argument('--out', default=None, help='출력 md 경로(생략 시 stdout)')
    args = ap.parse_args(argv)

    indexed = []
    todo_lines = []
    read_count = 0
    gi = 0

    for p in args.jsonl:
        if not os.path.exists(p):
            print(f'[warn] 입력 부재(건너뜀): {p}', file=sys.stderr)
            continue
        try:
            for text in read_jsonl_lines(p):
                indexed.append((gi, text))
                gi += 1
            read_count += 1
        except OSError as e:
            print(f'[warn] 읽기 실패(건너뜀): {p}: {e}', file=sys.stderr)

    for p in args.todo:
        if not os.path.exists(p):
            print(f'[warn] 입력 부재(건너뜀): {p}', file=sys.stderr)
            continue
        try:
            tl = read_text_lines(p)
            todo_lines.extend(tl)
            for ln in tl:
                indexed.append((gi, ln))
                gi += 1
            read_count += 1
        except OSError as e:
            print(f'[warn] 읽기 실패(건너뜀): {p}: {e}', file=sys.stderr)

    if read_count == 0:
        print('[error] 읽을 수 있는 입력이 없다(전 입력 부재).', file=sys.stderr)
        return 2

    md = build_markdown(indexed, todo_lines)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            fh.write(md)
    else:
        sys.stdout.write(md)
    return 0


if __name__ == '__main__':
    sys.exit(main())
