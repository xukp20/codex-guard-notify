---
description: Install or update codex-guard-notify hooks and Lark/Feishu notification wiring in ~/.codex.
---

# Install Guard Notify

Use `python3 scripts/install.py` from the repository root.

What it does:

- enables `codex_hooks`
- writes `~/.codex/hooks.json`
- sets `notify = ["python3", "<repo>/scripts/lark_notify.py"]`
- creates `~/.codex/lark_notify.json` if missing

After install, configure your webhook in `~/.codex/lark_notify.json`.
