#!/usr/bin/env python3
"""ezer_merge_check.py — 비파괴 병합 사전점검 도구 (OMC OPP-14 클린룸 포트).

`git merge-tree --write-tree` 로 대상 repo를 **전혀 변경하지 않고** 두 브랜치의
병합 가능성만 검사한다. 어떤 경우에도 대상 repo를 변경하는 git 명령
(merge/checkout/reset/clean 등)을 실행하지 않는다 — merge-tree·status·rev-parse 만 쓴다.
(merge-tree 는 결과 트리 객체 1개를 object DB에 쓰지만 HEAD·ref·index·worktree 는
불변이므로 비파괴다.)

서브커맨드
----------
check   --repo <path> --ours <branch> --theirs <branch>
    `git merge-tree --write-tree --name-only <ours> <theirs>` 를 비파괴 실행한다.
      clean → exit 0, stdout: {"clean": true, "tree": "<hash>"}
      충돌  → exit 4, stdout: {"clean": false, "conflicts": ["파일", ...]}

prepare --repo <path> --ours <branch> --theirs <branch>
    check 가 clean 이면 **실행하지 않고** master 집행용 머지 명령 문자열만 stdout 출력:
        git -C <repo> merge --no-ff <theirs>
    충돌이면 exit 4 (stdout 무출력, 충돌 파일은 stderr 안내).
    worktree 가 dirty(`git status --porcelain` 비어있지 않음)면 stderr 경고 1줄 추가
    한다(차단은 안 함 — 정보만).

공통 규칙
---------
- theirs 가 main 또는 master 면 exit 2 로 거부한다(OMC 동형 안전 — 보호 브랜치를
  병합원으로 지정 금지).
- 모든 subprocess 는 전건 list 인자·shell=False·timeout=30 으로 호출한다.

Exit 코드
---------
  0  clean(check) / 머지 명령 출력 성공(prepare)
  2  usage 오류 (인자 누락·잘못된 서브커맨드·theirs 가 main/master)
  3  repo 없음 · 브랜치 없음 · git 오류 · 시간초과
  4  병합 충돌
"""

import argparse
import json
import subprocess
import sys

_TIMEOUT = 30
# 병합원(theirs)으로 지정 금지하는 보호 브랜치 (ref 전체 형태도 방어)
_PROTECTED = ("main", "master", "refs/heads/main", "refs/heads/master")


def _git(repo, args):
    """대상 repo 에 대해 읽기 전용 git 명령을 실행한다.

    shell=False · 전건 list 인자 · timeout=30. 이 헬퍼로는 merge-tree·status·rev-parse
    만 호출하며, repo 를 변경하는 명령은 절대 넘기지 않는다.
    """
    return subprocess.run(
        ["git", "-C", repo] + args,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
    )


def _ref_exists(repo, ref):
    """repo 안에 커밋으로 해석되는 ref 가 있으면 True. repo 자체가 없어도 False."""
    r = _git(repo, ["rev-parse", "--verify", "--quiet", ref + "^{commit}"])
    return r.returncode == 0


def _merge_tree(repo, ours, theirs):
    """비파괴 merge-tree 실행 결과를 (status, data) 로 반환한다.

    반환: ("clean", "<tree hash>") | ("conflict", ["파일", ...])
    repo/브랜치 오류 등은 RuntimeError 로 올린다(호출부에서 exit 3 매핑).

    `git merge-tree --write-tree --name-only` 출력 형식(비-z):
        1행     = 결과 트리 OID
        이후    = 충돌 파일명(파일당 1줄, 빈 줄 전까지)
        빈 줄   = 구분자
        그 뒤   = 안내 메시지(로케일 의존 — 파싱하지 않음)
    exit 0=clean, 1=충돌, 그 외=오류.
    """
    r = _git(repo, ["merge-tree", "--write-tree", "--name-only", ours, theirs])
    lines = r.stdout.splitlines()
    if r.returncode == 0:
        tree = lines[0].strip() if lines else ""
        return ("clean", tree)
    if r.returncode == 1:
        conflicts = []
        for ln in lines[1:]:
            if ln == "":  # 빈 줄부터는 안내 메시지 — 파일 목록 끝
                break
            if ln not in conflicts:
                conflicts.append(ln)
        return ("conflict", conflicts)
    raise RuntimeError(r.stderr.strip() or "git merge-tree 오류")


def _resolve(repo, ours, theirs):
    """repo/브랜치 검증 후 merge-tree 결과를 반환하거나, 실패 시 exit 코드를 반환한다.

    반환: (status, data, None)  성공 — status 는 "clean"|"conflict"
          (None, None, 3)       repo/브랜치 없음 또는 git 오류
    """
    if not (_ref_exists(repo, ours) and _ref_exists(repo, theirs)):
        print(
            "repo 또는 브랜치를 찾을 수 없습니다: repo=%s ours=%s theirs=%s"
            % (repo, ours, theirs),
            file=sys.stderr,
        )
        return (None, None, 3)
    try:
        status, data = _merge_tree(repo, ours, theirs)
    except RuntimeError as e:
        print("git 오류: %s" % e, file=sys.stderr)
        return (None, None, 3)
    return (status, data, None)


def cmd_check(args):
    status, data, err = _resolve(args.repo, args.ours, args.theirs)
    if err is not None:
        return err
    if status == "clean":
        print(json.dumps({"clean": True, "tree": data}))
        return 0
    print(json.dumps({"clean": False, "conflicts": data}, ensure_ascii=False))
    return 4


def cmd_prepare(args):
    repo, theirs = args.repo, args.theirs
    status, data, err = _resolve(repo, args.ours, theirs)
    if err is not None:
        return err
    if status == "conflict":
        # 충돌이면 머지 명령을 만들지 않는다. stdout 은 비우고 충돌 파일만 안내.
        print("충돌로 머지 명령을 생성하지 않습니다: %s" % ", ".join(data), file=sys.stderr)
        return 4
    # clean → dirty worktree 경고(차단 안 함 — 정보만)
    st = _git(repo, ["status", "--porcelain"])
    if st.returncode == 0 and st.stdout.strip():
        print(
            "경고: 작업 트리에 커밋되지 않은 변경이 있습니다(dirty) — 병합 전 정리를 권장합니다.",
            file=sys.stderr,
        )
    # master 집행용 명령 문자열만 출력(여기서 실행하지 않는다)
    print("git -C %s merge --no-ff %s" % (repo, theirs))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="ezer_merge_check.py",
        description="비파괴 병합 사전점검 (merge-tree 기반 — 대상 repo 불변)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "prepare"):
        sp = sub.add_parser(name)
        sp.add_argument("--repo", required=True, help="대상 git repo 경로")
        sp.add_argument("--ours", required=True, help="기준(우리) 브랜치")
        sp.add_argument("--theirs", required=True, help="병합원(상대) 브랜치")
    args = p.parse_args(argv)  # 인자 오류는 argparse 가 exit 2

    # theirs 가 보호 브랜치면 거부(OMC 동형 안전)
    if args.theirs in _PROTECTED:
        print("main/master를 병합원으로 지정 금지", file=sys.stderr)
        return 2

    if args.cmd == "check":
        return cmd_check(args)
    return cmd_prepare(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.TimeoutExpired:
        print("git 명령 시간초과(30초)", file=sys.stderr)
        sys.exit(3)
