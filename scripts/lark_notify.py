#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from guard_common import clear_guard_files
from guard_common import load_success_marker_for_turn


DEFAULT_CONFIG_PATH = Path.home() / ".codex" / "lark_notify.json"
DEFAULT_TITLE = "Codex Turn Complete"
DEFAULT_MAX_MESSAGE_CHARS = 2800


def _read_json_file(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def load_settings() -> dict:
    config_path = Path(
        os.environ.get("CODEX_LARK_NOTIFY_CONFIG", str(DEFAULT_CONFIG_PATH))
    )
    file_settings = _read_json_file(config_path)

    webhook_url = (
        os.environ.get("CODEX_LARK_WEBHOOK_URL")
        or os.environ.get("LARK_WEBHOOK_URL")
        or os.environ.get("FEISHU_WEBHOOK_URL")
        or file_settings.get("webhook_url")
    )
    webhook_secret = (
        os.environ.get("CODEX_LARK_WEBHOOK_SECRET")
        or os.environ.get("LARK_WEBHOOK_SECRET")
        or os.environ.get("FEISHU_WEBHOOK_SECRET")
        or file_settings.get("webhook_secret")
    )
    title = (
        os.environ.get("CODEX_LARK_NOTIFY_TITLE")
        or file_settings.get("title")
        or DEFAULT_TITLE
    )
    max_message_chars = int(
        os.environ.get("CODEX_LARK_NOTIFY_MAX_MESSAGE_CHARS")
        or file_settings.get("max_message_chars")
        or DEFAULT_MAX_MESSAGE_CHARS
    )
    enabled_raw = os.environ.get("CODEX_LARK_NOTIFY_ENABLED")
    if enabled_raw is None:
        enabled = bool(file_settings.get("enabled", True))
    else:
        enabled = enabled_raw.lower() in {"1", "true", "yes", "on"}
    enabled_types = file_settings.get("enabled_types") or ["agent-turn-complete"]
    dry_run = os.environ.get("CODEX_LARK_NOTIFY_DRY_RUN", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    return {
        "enabled": enabled,
        "webhook_url": webhook_url,
        "webhook_secret": webhook_secret,
        "title": title,
        "max_message_chars": max_message_chars,
        "enabled_types": set(enabled_types),
        "dry_run": dry_run,
    }


def load_payload() -> dict:
    candidates = []
    if len(sys.argv) > 1:
        candidates.extend(reversed(sys.argv[1:]))
    if not sys.stdin.isatty():
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            candidates.append(stdin_text)

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def get_field(payload: dict, *names: str):
    for name in names:
        if name in payload and payload[name] is not None:
            return payload[name]
    return None


def trim_block(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def build_message(payload: dict, settings: dict) -> str:
    event_type = get_field(payload, "type") or "unknown"
    thread_id = get_field(payload, "thread-id", "thread_id")
    turn_id = get_field(payload, "turn-id", "turn_id")
    cwd = get_field(payload, "cwd")
    client = get_field(payload, "client")
    inputs = get_field(payload, "input-messages", "input_messages") or []
    if not isinstance(inputs, list):
        inputs = [str(inputs)]
    last_message = get_field(
        payload, "last-assistant-message", "last_assistant_message"
    ) or ""

    header = f"{settings['title']}: {event_type}"
    meta = []
    if cwd:
        meta.append(f"cwd: {cwd}")
    if thread_id:
        meta.append(f"thread: {thread_id}")
    if turn_id:
        meta.append(f"turn: {turn_id}")
    if client:
        meta.append(f"client: {client}")

    user_prompt = trim_block(inputs[-1], 600) if inputs else ""
    assistant_text = trim_block(last_message, settings["max_message_chars"])

    parts = [header]
    if meta:
        parts.append("\n".join(meta))
    if user_prompt:
        parts.append("Latest user input:\n" + user_prompt)
    if assistant_text:
        parts.append("Final assistant message:\n" + assistant_text)

    message = "\n\n".join(parts).strip()
    return trim_block(message, settings["max_message_chars"])


def build_guard_success_message(marker: dict, settings: dict) -> str:
    parts = ["Codex Guard Success"]
    meta = []
    if marker.get("cwd"):
        meta.append(f"cwd: {marker['cwd']}")
    if marker.get("session_id"):
        meta.append(f"session: {marker['session_id']}")
    if marker.get("turn_id"):
        meta.append(f"turn: {marker['turn_id']}")
    if meta:
        parts.append("\n".join(meta))
    if marker.get("goal_check_prompt"):
        parts.append(
            "Check target:\n"
            + trim_block(marker["goal_check_prompt"], settings["max_message_chars"])
        )
    if marker.get("completion_summary"):
        parts.append(
            "Completion summary:\n"
            + trim_block(marker["completion_summary"], settings["max_message_chars"])
        )
    if marker.get("full_final_text"):
        parts.append(
            "Final reply:\n"
            + trim_block(marker["full_final_text"], settings["max_message_chars"])
        )
    return trim_block("\n\n".join(parts).strip(), settings["max_message_chars"])


def sign_payload(secret: str) -> tuple[int, str]:
    timestamp = int(time.time())
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return timestamp, base64.b64encode(digest).decode("utf-8")


def post_to_lark(settings: dict, message: str) -> None:
    webhook_url = settings["webhook_url"]
    if not webhook_url:
        return

    body = {
        "msg_type": "text",
        "content": {
            "text": message,
        },
    }

    if settings["webhook_secret"]:
        timestamp, sign = sign_payload(settings["webhook_secret"])
        body["timestamp"] = timestamp
        body["sign"] = sign

    body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if settings["dry_run"]:
        sys.stdout.write(body_bytes.decode("utf-8") + "\n")
        return

    request = urllib.request.Request(
        webhook_url,
        data=body_bytes,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        response_body = response.read().decode("utf-8", errors="replace")
    try:
        result = json.loads(response_body) if response_body else {}
    except json.JSONDecodeError:
        result = {}
    if result.get("code") not in (None, 0):
        raise RuntimeError(
            f"lark webhook returned code={result.get('code')} msg={result.get('msg')}"
        )


def maybe_send_guard_success(settings: dict, payload: dict) -> None:
    if get_field(payload, "type") != "agent-turn-complete":
        return
    thread_id = get_field(payload, "thread-id", "thread_id")
    turn_id = get_field(payload, "turn-id", "turn_id")
    marker, marker_path = load_success_marker_for_turn(thread_id, turn_id)
    if not marker or not marker_path:
        return
    if not marker.get("notify_on_success", True):
        clear_guard_files(
            marker.get("session_id", thread_id or ""),
            remove_session=False,
            remove_runtime=False,
            remove_success=True,
        )
        return
    if not settings["webhook_url"]:
        return

    message = build_guard_success_message(marker, settings)
    if not message:
        return
    post_to_lark(settings, message)
    clear_guard_files(
        marker.get("session_id", thread_id or ""),
        remove_session=False,
        remove_runtime=False,
        remove_success=True,
    )


def main() -> int:
    settings = load_settings()
    payload = load_payload()
    event_type = get_field(payload, "type")
    if not payload:
        return 0

    try:
        if settings["enabled"] and event_type in settings["enabled_types"]:
            message = build_message(payload, settings)
            if message:
                post_to_lark(settings, message)
        maybe_send_guard_success(settings, payload)
    except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
        sys.stderr.write(f"codex lark notify failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
