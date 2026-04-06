#!/usr/bin/env python3
import json
import re
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


GUARD_ROOT = Path.home() / ".codex" / "guard"
SESSIONS_DIR = GUARD_ROOT / "sessions"
RUNTIME_DIR = GUARD_ROOT / "runtime"
DEFAULT_TEMPLATE = "已完成:[完成情况说明]"
DEFAULT_REGEX = r"^已完成:\s*(.+)$"
DEFAULT_MAX_AUTO_CONTINUE = 20
MAX_AUTO_CONTINUE_LIMIT = 200
RETENTION_SECONDS = 30 * 24 * 60 * 60
VALID_ACTIONS = {"set", "show", "off"}
VALID_PREFIXES = {">guard", "/guard", "@guard", "guard"}
VALID_FIELDS = {
    "prompt",
    "template",
    "regex",
    "auto_clear",
    "notify",
    "max_auto_continue",
}


class GuardError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def ensure_guard_dirs() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_old_runtime_files() -> None:
    ensure_guard_dirs()
    cutoff = time.time() - RETENTION_SECONDS
    for path in list(SESSIONS_DIR.glob("*.json")) + list(RUNTIME_DIR.glob("*.json")):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            continue


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, data: dict) -> None:
    ensure_guard_dirs()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp_path.replace(path)


def session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def runtime_path(session_id: str) -> Path:
    return RUNTIME_DIR / f"{session_id}.json"


def success_path(session_id: str) -> Path:
    return RUNTIME_DIR / f"{session_id}.success.json"


def load_session_guard(session_id: str) -> Optional[dict]:
    data = _read_json(session_path(session_id))
    return data or None


def load_runtime_state(session_id: str) -> dict:
    data = _read_json(runtime_path(session_id))
    return data or {
        "version": 1,
        "session_id": session_id,
        "attempts": 0,
        "last_turn_id": None,
        "last_checked_at": None,
        "last_assistant_message_preview": None,
        "last_match_ok": False,
        "last_match_capture": None,
        "exhausted": False,
    }


def save_session_guard(session_id: str, data: dict) -> None:
    _write_json(session_path(session_id), data)


def save_runtime_state(session_id: str, data: dict) -> None:
    _write_json(runtime_path(session_id), data)


def save_success_marker(session_id: str, data: dict) -> Path:
    path = success_path(session_id)
    _write_json(path, data)
    return path


def clear_guard_files(
    session_id: str,
    *,
    remove_session: bool = True,
    remove_runtime: bool = True,
    remove_success: bool = True,
) -> None:
    paths = []
    if remove_session:
        paths.append(session_path(session_id))
    if remove_runtime:
        paths.append(runtime_path(session_id))
    if remove_success:
        paths.append(success_path(session_id))
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue


def _normalize_text(text: str) -> str:
    return textwrap.dedent(text or "").strip()


def _is_top_level_field(line: str) -> bool:
    stripped = line.strip()
    if not stripped or line.startswith((" ", "\t")):
        return False
    if ":" not in line:
        return False
    key = line.split(":", 1)[0].strip()
    return key in VALID_FIELDS


def _parse_bool(value: str, field_name: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    raise GuardError(f"{field_name} must be true or false.")


def _parse_int(value: str, field_name: str) -> int:
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise GuardError(f"{field_name} must be an integer.") from exc
    if parsed < 1 or parsed > MAX_AUTO_CONTINUE_LIMIT:
        raise GuardError(
            f"{field_name} must be between 1 and {MAX_AUTO_CONTINUE_LIMIT}."
        )
    return parsed


def parse_guard_command(prompt_text: str) -> Optional[dict]:
    prompt = _normalize_text(prompt_text)
    if not prompt:
        return None
    lines = prompt.splitlines()
    first = lines[0].strip()
    parts = first.split()
    if not parts:
        return None
    if parts[0] not in VALID_PREFIXES:
        return None
    if len(parts) != 2 or parts[1] not in VALID_ACTIONS:
        raise GuardError("Usage: >guard set, >guard show, >guard off")

    action = parts[1]
    if action in {"show", "off"}:
        if any(line.strip() for line in lines[1:]):
            raise GuardError(f">guard {action} should not have extra content.")
        return {"action": action}

    fields = {}
    body_lines = lines[1:]
    i = 0
    while i < len(body_lines):
        line = body_lines[i]
        if not line.strip():
            i += 1
            continue
        if ":" not in line or line.startswith((" ", "\t")):
            raise GuardError(f"Cannot parse line: {line}")

        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.lstrip()
        if key not in VALID_FIELDS:
            raise GuardError(f"Unsupported field: {key}")
        if key in fields:
            raise GuardError(f"Duplicate field: {key}")

        if raw_value == "|":
            i += 1
            block_lines = []
            while i < len(body_lines):
                candidate = body_lines[i]
                if _is_top_level_field(candidate):
                    break
                block_lines.append(candidate)
                i += 1
            value = textwrap.dedent("\n".join(block_lines)).strip("\n")
        else:
            value = raw_value.strip()
            i += 1
        fields[key] = value

    goal_check_prompt = _normalize_text(fields.get("prompt", ""))
    if not goal_check_prompt:
        raise GuardError("prompt is required.")

    success_template_for_agent = _normalize_text(
        fields.get("template", DEFAULT_TEMPLATE)
    ) or DEFAULT_TEMPLATE
    success_regex = fields.get("regex", DEFAULT_REGEX).strip() or DEFAULT_REGEX
    auto_clear_on_success = _parse_bool(
        fields.get("auto_clear", "true"), "auto_clear"
    )
    notify_on_success = _parse_bool(fields.get("notify", "true"), "notify")
    max_auto_continue = _parse_int(
        fields.get("max_auto_continue", str(DEFAULT_MAX_AUTO_CONTINUE)),
        "max_auto_continue",
    )

    try:
        re.compile(success_regex, re.UNICODE | re.DOTALL)
    except re.error as exc:
        raise GuardError(f"regex failed to compile: {exc}") from exc

    return {
        "action": "set",
        "config": {
            "goal_check_prompt": goal_check_prompt,
            "success_template_for_agent": success_template_for_agent,
            "success_regex": success_regex,
            "auto_clear_on_success": auto_clear_on_success,
            "notify_on_success": notify_on_success,
            "max_auto_continue": max_auto_continue,
        },
    }


def build_guard_record(session_id: str, cwd: str, config: dict) -> dict:
    ts = now_iso()
    return {
        "version": 1,
        "enabled": True,
        "created_at": ts,
        "updated_at": ts,
        "session_id": session_id,
        "cwd": cwd,
        **config,
    }


def guard_summary(config: Optional[dict], runtime: Optional[dict] = None) -> str:
    if not config:
        return "No guard is enabled for this session."
    runtime = runtime or {}
    prompt_preview = config.get("goal_check_prompt", "")
    if len(prompt_preview) > 180:
        prompt_preview = prompt_preview[:179].rstrip() + "..."
    attempts = runtime.get("attempts", 0)
    max_auto_continue = config.get("max_auto_continue", DEFAULT_MAX_AUTO_CONTINUE)
    return "\n".join(
        [
            "Current guard configuration:",
            f"prompt={prompt_preview}",
            f"template={config.get('success_template_for_agent', DEFAULT_TEMPLATE)}",
            f"regex={config.get('success_regex', DEFAULT_REGEX)}",
            f"auto_clear={str(config.get('auto_clear_on_success', True)).lower()}",
            f"notify={str(config.get('notify_on_success', True)).lower()}",
            f"attempts={attempts}/{max_auto_continue}",
        ]
    )


def build_continue_prompt(config: dict) -> str:
    return "\n\n".join(
        [
            "[Guard Check Target]",
            config["goal_check_prompt"],
            "[If complete, reply using exactly this template]",
            config["success_template_for_agent"],
            "[If not complete]",
            "Do not summarize. Continue the remaining work.",
        ]
    )


def match_success(config: dict, final_text: Optional[str]) -> tuple[bool, Optional[str]]:
    text = (final_text or "").strip()
    if not text:
        return False, None
    pattern = re.compile(config["success_regex"], re.UNICODE | re.DOTALL)
    match = pattern.search(text)
    if not match:
        return False, None
    if match.lastindex:
        for index in range(1, match.lastindex + 1):
            captured = match.group(index)
            if captured is not None:
                captured = captured.strip()
                if captured:
                    return True, captured
    matched_text = match.group(0).strip()
    return True, matched_text if matched_text else None


def load_success_marker_for_turn(
    session_id: Optional[str], turn_id: Optional[str]
) -> tuple[Optional[dict], Optional[Path]]:
    candidate_paths = []
    if session_id:
        candidate_paths.append(success_path(session_id))
    for path in candidate_paths:
        data = _read_json(path)
        if data:
            return data, path
    if not turn_id:
        return None, None
    for path in RUNTIME_DIR.glob("*.success.json"):
        data = _read_json(path)
        if data.get("turn_id") == turn_id:
            return data, path
    return None, None
