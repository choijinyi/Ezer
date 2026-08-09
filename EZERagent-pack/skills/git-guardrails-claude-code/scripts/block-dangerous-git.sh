#!/usr/bin/env bash
# PreToolUse hook: block dangerous git commands (exit 2 = block, exit 0 = allow).
#
# Threat model: preventing *mistakes* by a cooperative agent — not a malicious
# adversary. Fundamental limits (documented, not hidden): interpreter indirection
# (`bash -c "git push"`, scripts), git aliases (`git co`), and shell-variable
# values that expand outside the inspected string cannot be caught here. The
# kill-switch remains the human reviewing the session.
#
# Design (defensive-security-gate playbook):
# - fail-closed: missing python3 / malformed JSON / unparseable shell / an
#   unresolvable token in a git invocation -> BLOCK.
# - real tokenization (shlex) instead of substring grep: quoting (`git "push"`),
#   flag injection (`git -C x push`), double spaces and argument reordering
#   (`git reset HEAD~1 --hard`) cannot dodge the matcher, and quoted prose
#   (`git commit -m "explain git push"`) cannot false-positive.
# - deny on the dangerous set; verify with the built-in battery: --self-test.

if ! command -v python3 >/dev/null 2>&1; then
  echo "git-guardrails: python3 missing — failing closed (blocking)" >&2
  exit 2
fi

if [ "${1:-}" = "--self-test" ]; then
  export GUARD_SELF_TEST=1
else
  GUARD_INPUT="$(cat)" || { echo "git-guardrails: cannot read stdin — failing closed" >&2; exit 2; }
  export GUARD_INPUT
fi

exec python3 - <<'PYEOF'
import json, os, shlex, sys

DANGEROUS_NOTE = {
    "push": "git push is blocked — pushing is the human's call",
    "reset --hard": "git reset --hard discards uncommitted work",
    "clean (force)": "git clean with a force flag deletes untracked files",
    "branch -D": "force-deleting branches loses commits",
    "checkout (discard)": "git checkout pathspec discard loses uncommitted work",
    "restore (worktree)": "git restore to the worktree loses uncommitted work",
    "unresolvable": "cannot safely interpret this git invocation — failing closed",
}

# git global flags that consume the next token (stable, documented set)
GIT_ARG_FLAGS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                 "--exec-path", "--super-prefix"}
WRAPPERS = {"command", "exec", "env", "sudo", "nohup", "time", "xargs"}


def is_separator(tok):
    return bool(tok) and set(tok) <= set(";&|()")


def short_letters(tok):
    """'-df' -> 'df' for short-option clusters; '' for long options/non-flags."""
    if len(tok) > 1 and tok[0] == "-" and tok[1] != "-":
        return tok[1:]
    return ""


def check_git_invocation(args):
    """args = tokens after 'git' up to the next separator. Block-reason or None."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] in GIT_ARG_FLAGS:
            i += 2  # flag consumes its value
        else:
            i += 1  # argless global flag (--no-pager, -p, --git-dir=x ...)
    if i >= len(args):
        return None  # flags only, no subcommand reached
    sub = args[i]
    rest = args[i + 1:]
    # unresolvable subcommand or substitution inside the invocation -> fail closed
    if sub.startswith("$") or "`" in sub:
        return "unresolvable"
    if any(t.startswith("$(") or "`" in t for t in rest):
        return "unresolvable"

    if sub == "push":
        return "push"
    if sub == "reset" and "--hard" in rest:
        return "reset --hard"
    if sub == "clean":
        if "--force" in rest or any("f" in short_letters(t) for t in rest):
            return "clean (force)"
    if sub == "branch":
        letters = [short_letters(t) for t in rest]
        if any("D" in l for l in letters):
            return "branch -D"
        if "--delete" in rest and "--force" in rest:
            return "branch -D"
        if any("d" in l and "f" in l for l in letters):
            return "branch -D"
    if sub == "checkout":
        if "--" in rest or "--force" in rest or any("f" in short_letters(t) for t in rest):
            return "checkout (discard)"
        if any(t in (".", ":/") or t.startswith("./") for t in rest):
            return "checkout (discard)"
    if sub == "restore":
        # only the pure index form (--staged without --worktree) is non-destructive
        if "--staged" not in rest or "--worktree" in rest:
            return "restore (worktree)"
    return None


def next_separator(tokens, start):
    for j in range(start + 1, len(tokens)):
        if is_separator(tokens[j]):
            return j
    return len(tokens)


def check_command(command):
    """Return block-reason or None for a full shell command string."""
    # newline separates commands but shlex folds it into whitespace
    command = command.replace("\n", " ; ").replace("\r", " ")
    # strip zero-width chars that could visually split the 'git' word
    for zw in ("​", "‌", "‍", "﻿"):
        command = command.replace(zw, "")
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return "unresolvable"  # unmatched quote etc. -> fail closed

    cmd_pos = True
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if is_separator(tok):
            cmd_pos = True
            i += 1
            continue
        if tok and set(tok) <= set("<>"):
            i += 2  # redirection operator + target — command position unchanged
            continue
        if cmd_pos:
            # skip env assignments and wrappers to find the real command word
            name = tok.split("=", 1)[0]
            if "=" in tok and name and name.replace("_", "").isalnum():
                i += 1
                continue
            if tok in WRAPPERS:
                i += 1
                continue
            if tok == "git" or tok.endswith("/git"):
                reason = check_git_invocation(tokens[i + 1:next_separator(tokens, i)])
                if reason:
                    return reason
            cmd_pos = False
        i += 1
    return None


def main():
    raw = os.environ.get("GUARD_INPUT", "")
    try:
        data = json.loads(raw)
    except ValueError:
        print("git-guardrails: malformed hook JSON — failing closed", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict):
        print("git-guardrails: unexpected hook JSON shape — failing closed", file=sys.stderr)
        sys.exit(2)
    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else ""
    if not isinstance(command, str) or not command:
        sys.exit(0)
    reason = check_command(command)
    if reason:
        print("git-guardrails BLOCKED: %s" % DANGEROUS_NOTE[reason], file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


def self_test():
    blocked = [
        "git push origin main",
        "git -C /tmp/repo push origin main",
        "git --no-pager push",
        "git  push",
        'git "push"',
        "git reset HEAD~1 --hard",
        "git reset --hard HEAD~1",
        "git clean -df",
        "git clean -f",
        "git clean --force",
        "git clean -xdf",
        "git branch --delete --force foo",
        "git branch -D foo",
        "git branch -df foo",
        "git checkout -- .",
        "git checkout .",
        "git checkout -f main",
        "git restore --worktree --source=HEAD :/",
        "git restore file.txt",
        "cd /x && git push",
        "echo ok; git push",
        "true && (git push)",
        "echo $(git push)",
        "env FOO=1 git push",
        "FOO=1 git push",
        "sudo git push",
        "git $CMD",          # variable subcommand -> fail closed
        "git 'push",         # unmatched quote -> fail closed
        "/usr/bin/git push",
        "git -c user.name=x push",
        "> /tmp/log git push",
    ]
    allowed = [
        "git status",
        "git log --oneline",
        'git commit -m "explain git push usage"',
        'echo "git clean -f is dangerous"',
        "git checkout main",
        "git checkout -b feature",
        "git restore --staged file.txt",
        "git reset HEAD~1",
        "git reset --soft HEAD~1",
        "git branch -d merged-branch",
        "git clean -n",
        "ls && echo git push",   # 'git push' is an echo argument, not a command
        "npm test",
        "git diff",
        "git push-to-deploy-helper",  # unknown subcommand, not 'push'
        "git stash list",
    ]
    fails = []
    for cmd in blocked:
        if check_command(cmd) is None:
            fails.append("BYPASS: %r" % cmd)
    for cmd in allowed:
        r = check_command(cmd)
        if r is not None:
            fails.append("FALSE-POSITIVE(%s): %r" % (r, cmd))
    if fails:
        print("\n".join(fails), file=sys.stderr)
        print("self-test: %d failure(s)" % len(fails), file=sys.stderr)
        sys.exit(1)
    print("self-test OK: %d blocked · %d allowed · fail-closed verified"
          % (len(blocked), len(allowed)))
    sys.exit(0)


if os.environ.get("GUARD_SELF_TEST"):
    self_test()
else:
    main()
PYEOF
