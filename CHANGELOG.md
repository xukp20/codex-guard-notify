# Changelog

## v0.1.0 - 2026-04-06

- Added session-scoped completion guards for Codex hooks.
- Added `>guard set`, `>guard show`, `>guard off`, and `>guard reset`.
- Added structured success matching with configurable template and regex.
- Added `Stop` hook continuation logic with retry limits and auto-clear.
- Added optional auto-reset of guard attempts on later manual user input.
- Added Lark/Feishu webhook notifications for guard success.
- Added an installer that merges into existing `~/.codex/config.toml` and `~/.codex/hooks.json`.
- Added plugin manifest, examples, and installation skill scaffolding.
