# codex-guard-notify

Session-scoped completion guards and Lark/Feishu notifications for Codex hooks.

This repository packages a practical Codex workflow for long-running tasks:

- `>guard set` configures a completion guard for the current session.
- A `Stop` hook checks the final assistant message against a success pattern.
- If the pattern does not match, Codex is blocked from stopping and is prompted to continue.
- When the pattern matches, the guard succeeds and an optional Lark/Feishu notification is sent.

## What it does

- Session-local guard state keyed by Codex `session_id`
- Structured success matching with a configurable regex
- Automatic continuation until success or a max retry limit
- Auto-clear on success so old guards do not accumulate
- Optional final-only Lark/Feishu success notifications
- Optional ordinary `notify` support, disabled by default

## Current scope

This project is built around Codex hooks, not around a fully self-contained plugin runtime.

It includes a plugin manifest at [`.codex-plugin/plugin.json`](./.codex-plugin/plugin.json), but current Codex runtime support for plugin-packaged hooks is not fully closed-loop. In practice, you should install the scripts and wire them through `~/.codex/hooks.json` and `~/.codex/config.toml`.

## Layout

- [`scripts/guard_common.py`](./scripts/guard_common.py): shared parsing, state, and matching helpers
- [`scripts/guard_control.py`](./scripts/guard_control.py): `UserPromptSubmit` hook for `>guard set|show|off`
- [`scripts/guard_stop.py`](./scripts/guard_stop.py): `Stop` hook for continuation and success detection
- [`scripts/lark_notify.py`](./scripts/lark_notify.py): Lark/Feishu webhook notifier
- [`scripts/install.py`](./scripts/install.py): minimal installer for hooks and notify wiring
- [`examples/hooks.json`](./examples/hooks.json): example hooks config
- [`examples/config.toml`](./examples/config.toml): example Codex config fragment
- [`examples/lark_notify.example.json`](./examples/lark_notify.example.json): example Lark notify config

## Install

Run:

```bash
python3 scripts/install.py
```

This will:

- enable `codex_hooks` in `~/.codex/config.toml`
- set or update top-level `notify = ["python3", "<repo>/scripts/lark_notify.py"]`
- merge `UserPromptSubmit` and `Stop` entries into `~/.codex/hooks.json`
- create `~/.codex/lark_notify.json` if it does not already exist

The installer is intentionally conservative:

- it preserves existing files as `.bak.<timestamp>`
- it merges into existing `config.toml` and `hooks.json` instead of overwriting them wholesale
- it does not inject your real webhook
- it leaves ordinary notify disabled by default

## Lark/Feishu config

Copy the example into `~/.codex/lark_notify.json` and fill in your webhook:

```json
{
  "enabled": false,
  "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/your-webhook",
  "webhook_secret": "",
  "title": "Codex",
  "enabled_types": ["agent-turn-complete"],
  "max_message_chars": 2800
}
```

Recommended default:

- keep `enabled=false`
- let guard-success notifications send independently

That gives you final-only notifications for guarded sessions, while suppressing ordinary turn-complete spam.

## Usage

Set a guard for the current session:

```text
>guard set
prompt: |
  检查一下是不是三个任务都完成了。
template: |
  已完成:[完成情况说明]
regex: ^已完成:\s*(.+)$
auto_clear: true
notify: true
max_auto_continue: 20
```

Show current guard:

```text
>guard show
```

Disable current guard:

```text
>guard off
```

Notes:

- In interactive Codex TUI, prefer `>guard`.
- `/guard` may collide with built-in slash command parsing.
- `template` is what the model should output on success.
- `regex` is what the hook actually matches.

## Success format

Default success template:

```text
已完成:[完成情况说明]
```

Default success regex:

```regex
^已完成:\s*(.+)$
```

If the final assistant message matches, the guard succeeds. The first non-empty capture group is used as the completion summary in the final notification.

## State files

Guard state is stored under `~/.codex/guard/`:

- `sessions/<session_id>.json`
- `runtime/<session_id>.json`
- `runtime/<session_id>.success.json`

With `auto_clear: true`, the session guard is removed immediately after a successful match.

## Notify behavior

`lark_notify.py` has two paths:

1. Ordinary `notify`
   - controlled by `enabled` in `~/.codex/lark_notify.json`
   - disabled by default in this repo

2. Guard-success notify
   - triggered by a success marker written by `guard_stop.py`
   - ignores ordinary `enabled`
   - only requires:
     - a valid webhook URL
     - `notify: true` in the session guard

This is the recommended default for long-running guarded sessions.

## Validation

Basic syntax check:

```bash
python3 -m py_compile scripts/*.py
```

## Limitations

- Codex TUI currently compresses hook feedback visually, so multi-line hook messages may appear flattened in the UI.
- `codex exec` does not display full hook feedback text in its human-readable output.
- Current Codex runtime plugin support is strongest for skills, MCP servers, and apps. Hook packaging is still best treated as an install-time wiring step.
