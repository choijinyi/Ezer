#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EZERagent_docsdiff — 변경된 줄만 모은 docs-diff 생성기 (하네스 7기법 N5).

출처: 외부 수집 지식(YouTube 4JtB_QvKT8w·바이브마피아 최수민) — 오너 SOT 아님.

영상 원리: Task 첫 단계는 무조건 "문서 업데이트". 업데이트 후 스크립트로 "변경된 정확한
내용"만 취합해 docs-diff 파일을 만들고("삭제된 내용은 없고 248번째 줄에 이 내용이 추가됐다"),
이후 단계들이 스펙 변경분만 콤팩트하게 참조한다. 스펙 문서가 길어져도 "추가된 줄만 들어가니
강조가 확실"해져 에이전트가 스펙을 제멋대로 해석해 어긋나게 구현하는 spec-drift를 차단한다.

이 도구는 그 취합 단계를 결정론으로 환원한다 — git diff의 추가/변경된 줄(+ 라인, NEW 파일
라인번호 포함)만 뽑아 마크다운으로 낸다(LLM 자연어 재추론 금지 — 출력만이 사실).

서브커맨드 없음(단일 동작):
  --paths <file...> [--base <git-ref>] [--out <file>]
      지정 경로들의 `git diff [base]`에서 추가/변경된 줄만 추출해 마크다운 생성.
      base 기본 HEAD. out 기본 stdout. git repo 아니면 명확한 에러 + exit 2.
      출력 형식: `## <path>` / `- L<n>: <추가/변경된 줄 내용>`.
      변경 없으면 "변경 없음"을 명시(빈 출력로 침묵하지 않음).

exit: 0=정상 산출(변경 없음 포함) / 2=git repo 아님·git 부재·인자 오류.

의존성: 파이썬 표준 라이브러리 + PATH의 git.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys


def pack_dir():
    for key in ("EZERAGENT_PACK_DIR",):
        v = os.environ.get(key, "")
        if v:
            return v
    return os.path.join(os.path.expanduser("~"), ".EZERagent/pack")


# ── unified diff 파싱 (순수 함수 — self-test가 밀폐 검증) ──
# 영상: "삭제된 내용은 없고 248번째 줄에 이 내용이 추가됐다" → 추가/변경된 줄(+)만,
# NEW 파일의 라인번호와 함께. 삭제(-)·문맥( ) 줄은 제외(강조는 추가분에 둔다).
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_added_lines(diff_text):
    """unified diff 텍스트 → [(new_lineno, content), ...] 추가/변경된 줄만.

    git diff 한 파일분(@@ 헤더로 시작하는 hunk들)을 받아 '+' 줄의 NEW 파일 라인번호를
    hunk 헤더(@@ -a,b +c,d @@)의 시작값에서부터 세어 부여한다. '+++ '(파일 헤더)는 제외.
    """
    out = []
    new_lineno = None
    for ln in diff_text.splitlines():
        m = HUNK_RE.match(ln)
        if m:
            new_lineno = int(m.group(1))
            continue
        if new_lineno is None:
            continue  # 아직 hunk 진입 전(파일 헤더 등)
        if ln.startswith("+++"):
            continue  # 파일 경로 헤더는 '+' 줄이 아니다
        if ln.startswith("+"):
            out.append((new_lineno, ln[1:]))
            new_lineno += 1
        elif ln.startswith("-"):
            pass  # 삭제 줄은 NEW 라인번호를 진척시키지 않는다
        elif ln.startswith("\\"):
            pass  # "\ No newline at end of file" — 라인번호 무관
        else:
            # 문맥 줄(' ' 또는 빈 줄=문맥의 빈 라인) — NEW 라인번호만 진척
            new_lineno += 1
    return out


def git_repo_root(cwd):
    """cwd가 속한 git repo의 루트 절대경로. git repo 아니거나 git 부재면 None."""
    git = shutil.which("git")
    if not git:
        return None
    try:
        r = subprocess.run([git, "rev-parse", "--show-toplevel"],
                           cwd=cwd, capture_output=True, timeout=10)
        if r.returncode != 0:
            return None
        return r.stdout.decode("utf-8", "replace").strip() or None
    except Exception:
        return None


def git_diff_for_path(root, base, path):
    """단일 경로의 `git diff <base> -- <path>` 텍스트(untracked 포함). 실패 시 ""."""
    git = shutil.which("git")
    if not git:
        return ""
    try:
        # untracked(새 파일)도 추가 줄로 잡으려면 --no-index 비교가 필요하나, 영상 맥락은
        # "문서 업데이트 후 변경분"이므로 git diff(작업트리 vs base)를 기본으로 한다.
        # 새 파일이 아직 add 안 됐으면 git이 추적하지 않아 diff가 비므로, intent-to-add를
        # 적용한 것과 동등하게 보이도록 --no-index 폴백을 추가한다(추적 안 된 신규 파일 대비).
        r = subprocess.run([git, "diff", base, "--", path],
                           cwd=root, capture_output=True, timeout=60)
        text = r.stdout.decode("utf-8", "replace")
        if text.strip():
            return text
        # 추적되지 않는 신규 파일: /dev/null 대비 --no-index로 전체를 추가 줄로 본다.
        abspath = path if os.path.isabs(path) else os.path.join(root, path)
        if os.path.isfile(abspath):
            chk = subprocess.run([git, "ls-files", "--error-unmatch", "--", path],
                                 cwd=root, capture_output=True, timeout=10)
            if chk.returncode != 0:  # 추적되지 않음 → 신규 파일
                ni = subprocess.run(
                    [git, "diff", "--no-index", "--", os.devnull, abspath],
                    cwd=root, capture_output=True, timeout=60)
                return ni.stdout.decode("utf-8", "replace")
        return text
    except Exception:
        return ""


def rel_to_root(root, path):
    """경로를 repo 루트 기준 상대경로로 정규화(출력 헤더 일관성).

    macOS는 git rev-parse가 /private/var(realpath)를, 입력은 /var(symlink)를 줄 수 있어
    양쪽을 realpath로 맞춘 뒤 relpath한다. 그래도 루트 밖이면('../' 시작) basename으로
    강등 — 헤더에 긴 '../../..' 탈출 경로가 박히지 않게 한다."""
    abspath = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
    abspath = os.path.realpath(abspath)
    root_real = os.path.realpath(root)
    try:
        rel = os.path.relpath(abspath, root_real)
    except ValueError:
        return os.path.basename(path)
    if rel.startswith(".."):
        return os.path.basename(path)
    return rel


def build_docs_diff(root, base, paths):
    """docs-diff 마크다운 본문 생성(순수 — root/base/paths만 의존). 변경 0이면 None 섹션."""
    sections = []
    for p in paths:
        diff_text = git_diff_for_path(root, base, p)
        added = parse_added_lines(diff_text)
        rel = rel_to_root(root, p)
        sections.append((rel, added))
    lines = []
    lines.append("# docs-diff (변경/추가된 줄만 — base: %s)" % base)
    lines.append("")
    lines.append("> 출처 기법: 외부 수집 지식(영상 4JtB_QvKT8w·바이브마피아 최수민) — "
                 "오너 SOT 아님. 이후 단계는 이 변경분만 콤팩트 참조해 spec-drift를 차단한다.")
    lines.append("")
    any_change = False
    for rel, added in sections:
        lines.append("## %s" % rel)
        if added:
            any_change = True
            for n, content in added:
                lines.append("- L%d: %s" % (n, content))
        else:
            lines.append("- (변경 없음)")
        lines.append("")
    if not any_change:
        lines.append("**변경 없음** — base(%s) 대비 추가/변경된 줄이 없다." % base)
    return "\n".join(lines).rstrip() + "\n"


def cmd_diff(args):
    # 인자 위생: --paths 비면 argparse가 막지만, 방어적으로 한 번 더.
    if not args.paths:
        print("[docsdiff] --paths 에 최소 1개 경로가 필요하다.", file=sys.stderr)
        return 2
    # git repo 판정은 첫 경로의 디렉터리(없으면 cwd) 기준 — 명확한 에러 + exit 2.
    first = args.paths[0]
    probe = os.path.dirname(os.path.abspath(first)) if os.path.dirname(first) else os.getcwd()
    if not os.path.isdir(probe):
        probe = os.getcwd()
    root = git_repo_root(probe)
    if root is None:
        if shutil.which("git") is None:
            print("[docsdiff] git 을 찾을 수 없다 — git 설치 후 재실행하라.", file=sys.stderr)
        else:
            print("[docsdiff] git repo가 아니다(%s) — git 저장소 안에서 실행하라."
                  % probe, file=sys.stderr)
        return 2
    body = build_docs_diff(root, args.base, args.paths)
    if args.out:
        out_dir = os.path.dirname(os.path.abspath(args.out))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(body)
        print("docs-diff 기록: %s" % args.out)
    else:
        sys.stdout.write(body)
    return 0


def cmd_self_test():
    """순수 로직 자기검증 (git 의존 없음) — preflight가 호출. assert 실패는 exit 1."""
    try:
        # (a) 기본 hunk: +248 시작, 추가 1줄
        diff = (
            "diff --git a/SPEC.md b/SPEC.md\n"
            "--- a/SPEC.md\n"
            "+++ b/SPEC.md\n"
            "@@ -247,3 +247,4 @@ ctx\n"
            " 문맥줄A\n"
            "+248번째에 추가된 줄\n"
            " 문맥줄B\n"
        )
        got = parse_added_lines(diff)
        assert got == [(248, "248번째에 추가된 줄")], "기본 추가줄 라인번호 오류: %r" % got
        # (b) 삭제(-) 줄은 NEW 라인번호를 진척시키지 않는다 + 제외된다
        diff2 = (
            "@@ -10,3 +10,3 @@\n"
            " a\n"
            "-삭제된 줄\n"
            "+교체된 줄\n"
            " b\n"
        )
        got2 = parse_added_lines(diff2)
        assert got2 == [(11, "교체된 줄")], "삭제 무시·교체 라인번호 오류: %r" % got2
        # (c) 다중 hunk: 라인번호가 hunk마다 재설정된다
        diff3 = (
            "@@ -1,1 +1,2 @@\n"
            " head\n"
            "+첫 추가\n"
            "@@ -100,1 +101,2 @@\n"
            " mid\n"
            "+둘째 추가\n"
        )
        got3 = parse_added_lines(diff3)
        assert got3 == [(2, "첫 추가"), (102, "둘째 추가")], "다중 hunk 라인번호 오류: %r" % got3
        # (d) +++ 파일 헤더는 추가 줄로 오인하지 않는다
        diff4 = (
            "--- a/x\n"
            "+++ b/x\n"
            "@@ -1,0 +1,1 @@\n"
            "+진짜 추가\n"
        )
        got4 = parse_added_lines(diff4)
        assert got4 == [(1, "진짜 추가")], "+++ 헤더 오인: %r" % got4
        # (e) 변경 없음(빈 diff) → 빈 리스트
        assert parse_added_lines("") == [], "빈 diff에서 추가줄 오탐"
        # (f) "\ No newline at end of file" 줄은 라인번호에 영향 없다
        diff5 = (
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
            "\\ No newline at end of file\n"
        )
        assert parse_added_lines(diff5) == [(1, "new")], "no-newline 마커 처리 오류"
    except AssertionError as e:
        print("EZERagent_docsdiff self-test FAIL: %s" % e, file=sys.stderr)
        return 1
    print("EZERagent_docsdiff self-test OK (hunk 라인번호·삭제 무시·다중 hunk·+++ 헤더·빈 diff)")
    return 0


def main():
    # preflight 호환: `--self-test`는 인자 없이도 동작해야 한다(가로채기).
    if "--self-test" in sys.argv:
        return cmd_self_test()
    ap = argparse.ArgumentParser(
        description="변경/추가된 줄만 모은 docs-diff 생성기(하네스 N5)")
    ap.add_argument("--paths", nargs="+", required=True, metavar="FILE",
                    help="docs-diff를 낼 파일 경로(1개 이상)")
    ap.add_argument("--base", default="HEAD",
                    help="비교 기준 git-ref (기본 HEAD)")
    ap.add_argument("--out", default=None,
                    help="출력 파일(기본 stdout) — 디렉터리 자동 생성")
    args = ap.parse_args()
    return cmd_diff(args)


if __name__ == "__main__":
    sys.exit(main())
