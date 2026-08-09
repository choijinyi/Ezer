---
name: git-guardrails-claude-code
description: Set up Claude Code hooks to block dangerous git commands (push, reset --hard, clean, branch -D, etc.) before they execute. Use when user wants to prevent destructive git operations, add git safety hooks, or block git push/reset in Claude Code.
---

# Setup Git Guardrails

Sets up a PreToolUse hook that intercepts and blocks dangerous git commands before Claude executes them.

## What Gets Blocked

- `git push` (all variants including `--force`)
- `git reset --hard`
- `git clean -f` / `git clean -fd`
- `git branch -D`
- `git checkout .` / `git restore .`

When blocked, Claude sees a message telling it that it does not have authority to access these commands.

## Steps

### 1. Ask scope

Ask the user: install for **this project only** (`.claude/settings.json`) or **all projects** (`~/.claude/settings.json`)?

### 2. Copy the hook script

The bundled script is at: `${EZERAGENT_PACK_DIR:-$HOME/.EZERagent/pack}/skills/git-guardrails-claude-code/scripts/block-dangerous-git.sh`

**Requires `python3` on PATH** (the gate tokenizes the command instead of substring-matching; it fails closed — blocks — if python3 is missing). No jq needed.

Copy it to the target location based on scope:

- **Project**: `.claude/hooks/block-dangerous-git.sh`
- **Global**: `~/.claude/hooks/block-dangerous-git.sh`

Make it executable with `chmod +x`.

### 3. Add hook to settings

Add to the appropriate settings file:

**Project** (`.claude/settings.json`):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/block-dangerous-git.sh"
          }
        ]
      }
    ]
  }
}
```

**Global** (`~/.claude/settings.json`):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/block-dangerous-git.sh"
          }
        ]
      }
    ]
  }
}
```

If the settings file already exists, merge the hook into existing `hooks.PreToolUse` array — don't overwrite other settings.

### 4. Ask about customization

Ask if user wants to add or remove rules from the blocked set. Edit the rule functions in the copied script accordingly (`check_git_invocation`), and add matching cases to the `--self-test` battery.

### 5. Verify

Run the built-in battery — it includes the bypass vectors (flag injection `git -C x push`, quoting `git "push"`, reordering `git reset HEAD~1 --hard`, wrappers `sudo`/`env`) and false-positive controls (`git commit -m "explain git push"`):

```bash
<path-to-script> --self-test
```

Must print `self-test OK`. Then spot-check the live contract:

```bash
echo '{"tool_input":{"command":"git push origin main"}}' | <path-to-script>   # exit 2, BLOCKED on stderr
echo '{"tool_input":{"command":"git status"}}' | <path-to-script>             # exit 0
```

## Known limits (by design)

The threat model is preventing *mistakes*, not stopping a determined adversary. Interpreter indirection (`bash -c "git push"`), git aliases (`git co`), and shell variables that expand outside the inspected string are not caught — the human reviewing the session remains the kill-switch.
