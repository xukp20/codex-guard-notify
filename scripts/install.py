#!/usr/bin/env python3
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_if_exists(path: Path) -> None:
    if not path.exists():
        return
    backup_path = path.with_name(f"{path.name}.bak.{now_tag()}")
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"existing JSON is invalid: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"expected a JSON object in {path}")
    return data


def _managed_group(command: str, timeout: int) -> dict:
    return {
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": timeout,
            }
        ]
    }


def _entry_contains_script(entry: dict, script_name: str) -> bool:
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    needle = f"/scripts/{script_name}"
    for hook in hooks:
        if not isinstance(hook, dict):
            continue
        command = hook.get("command")
        if isinstance(command, str) and needle in command:
            return True
    return False


def write_hooks(repo_root: Path, codex_home: Path) -> Path:
    hooks_path = codex_home / "hooks.json"
    existing = _read_json(hooks_path) if hooks_path.exists() else {}
    backup_if_exists(hooks_path)

    hooks = dict(existing)
    hooks_map = hooks.get("hooks")
    if hooks_map is None:
        hooks_map = {}
    if not isinstance(hooks_map, dict):
        raise RuntimeError("existing hooks.json has a non-object 'hooks' field")

    user_prompt_submit_group = _managed_group(
        f"python3 {repo_root / 'scripts' / 'guard_control.py'}", 10
    )
    stop_group = _managed_group(
        f"python3 {repo_root / 'scripts' / 'guard_stop.py'}", 20
    )

    managed = {
        "UserPromptSubmit": (user_prompt_submit_group, "guard_control.py"),
        "Stop": (stop_group, "guard_stop.py"),
    }

    for event_name, (group, script_name) in managed.items():
        entries = hooks_map.get(event_name)
        if entries is None:
            entries = []
        if not isinstance(entries, list):
            raise RuntimeError(f"hooks.{event_name} must be an array")
        filtered = [
            entry
            for entry in entries
            if not (isinstance(entry, dict) and _entry_contains_script(entry, script_name))
        ]
        filtered.append(group)
        hooks_map[event_name] = filtered

    hooks["hooks"] = hooks_map
    hooks_path.write_text(
        json.dumps(hooks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return hooks_path


def _split_lines_keepends(text: str) -> list[str]:
    return text.splitlines(keepends=True) if text else []


def _is_section_header(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r"^\[[^\[\]].*\]$", stripped))


def _section_name(line: str) -> str | None:
    stripped = line.strip()
    match = re.match(r"^\[([^\[\]].*)\]$", stripped)
    if not match:
        return None
    return match.group(1)


def _merge_top_level_notify(lines: list[str], notify_line: str) -> list[str]:
    result = []
    section = None
    replaced = False
    for line in lines:
        section_name = _section_name(line)
        if section_name is not None:
            section = section_name
        if (
            section is None
            and re.match(r"^notify\s*=", line.strip())
            and not line.lstrip().startswith("#")
        ):
            if not replaced:
                result.append(notify_line)
                replaced = True
            continue
        result.append(line)
    if not replaced:
        if result and not result[0].startswith("\n"):
            result.insert(0, "\n")
        result.insert(0, notify_line)
    return result


def _merge_features_codex_hooks(lines: list[str]) -> list[str]:
    features_start = None
    features_end = None
    for index, line in enumerate(lines):
        if _section_name(line) == "features":
            features_start = index
            continue
        if features_start is not None and _is_section_header(line):
            features_end = index
            break
    if features_start is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.extend(["[features]\n", "codex_hooks = true\n"])
        return lines

    if features_end is None:
        features_end = len(lines)

    found = False
    for index in range(features_start + 1, features_end):
        stripped = lines[index].strip()
        if stripped.startswith("codex_hooks") and not stripped.startswith("#"):
            lines[index] = "codex_hooks = true\n"
            found = True
            break
    if not found:
        insert_at = features_end
        if insert_at > features_start + 1 and lines[insert_at - 1].strip():
            lines.insert(insert_at, "codex_hooks = true\n")
        else:
            lines.insert(insert_at, "codex_hooks = true\n")
    return lines


def write_config(repo_root: Path, codex_home: Path) -> Path:
    config_path = codex_home / "config.toml"
    existing_text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    backup_if_exists(config_path)
    notify_script = repo_root / "scripts" / "lark_notify.py"
    notify_line = f'notify = ["python3", "{notify_script}"]\n'
    lines = _split_lines_keepends(existing_text)
    lines = _merge_top_level_notify(lines, notify_line)
    lines = _merge_features_codex_hooks(lines)
    config_text = "".join(lines)
    if config_text and not config_text.endswith("\n"):
        config_text += "\n"
    config_path.write_text(config_text, encoding="utf-8")
    return config_path


def ensure_notify_config(codex_home: Path) -> Path:
    notify_path = codex_home / "lark_notify.json"
    if notify_path.exists():
        return notify_path
    notify_path.write_text(
        json.dumps(
            {
                "enabled": False,
                "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/your-webhook",
                "webhook_secret": "",
                "title": "Codex",
                "enabled_types": ["agent-turn-complete"],
                "max_message_chars": 2800,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return notify_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--codex-home", default=str(Path.home() / ".codex"), help="Path to ~/.codex"
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    codex_home = Path(args.codex_home).expanduser().resolve()
    codex_home.mkdir(parents=True, exist_ok=True)

    hooks_path = write_hooks(repo_root, codex_home)
    config_path = write_config(repo_root, codex_home)
    notify_path = ensure_notify_config(codex_home)

    print(f"installed hooks: {hooks_path}")
    print(f"installed config: {config_path}")
    print(f"notify config: {notify_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
