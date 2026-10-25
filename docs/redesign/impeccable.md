# Using impeccable for the 1.0 redesign

[impeccable](https://github.com/pbakaus/impeccable) (Apache 2.0) is a design skill plus a detector engine. We use it to check mocks and pages: `detect` (mechanical scan), `critique`, `typeset`, `polish` and the other references in its skill.

## In a Claude Code cloud session

The host impeccable.style is not reachable from the cloud, but GitHub is:

```bash
git clone --depth 1 https://github.com/pbakaus/impeccable.git /tmp/impeccable
/tmp/impeccable/.claude/skills/impeccable/scripts/impeccable --version   # downloads the engine once
/tmp/impeccable/.claude/skills/impeccable/scripts/impeccable detect --json docs/redesign/mocks/
```

The skill text (`.claude/skills/impeccable/SKILL.md` and `reference/*.md`) is read directly from the clone. Do not copy it into this repository.

## Locally (Windows, macOS, Linux)

In Claude Code:

```
/plugin marketplace add pbakaus/impeccable
```

Then open `/plugin` and install Impeccable. Alternative with Node: `npx impeccable install --providers=claude --scope=global`. Both install the same skill; on Windows the launcher is `impeccable.cmd`.

Tested version: 4.7.0 (21.10.2026).
