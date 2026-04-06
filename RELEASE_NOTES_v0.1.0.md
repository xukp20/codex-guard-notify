# codex-guard-notify v0.1.0

Initial public release.

## Included

- Session-local completion guards keyed by Codex `session_id`
- `UserPromptSubmit` guard control via `>guard set|show|off|reset`
- `Stop` hook enforcement with retry-limited continuation
- Structured success matching with template and regex
- Auto-clear on successful completion
- Optional auto-reset of attempts on later manual user input
- Final-only Lark/Feishu notifications for guarded sessions
- Minimal installer for wiring hooks and notify into `~/.codex`

## Notes

- Ordinary `notify` is disabled by default.
- Guard-success notifications can still be sent when a webhook is configured.
- In interactive Codex TUI, prefer `>guard` over `/guard`.
- Current Codex plugin runtime support is strongest for skills, MCP servers, and apps; this project should still be installed through hooks/config wiring.
