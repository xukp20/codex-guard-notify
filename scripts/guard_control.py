#!/usr/bin/env python3
import json
import sys

from guard_common import (
    GuardError,
    build_guard_record,
    cleanup_old_runtime_files,
    clear_guard_files,
    ensure_guard_dirs,
    guard_summary,
    load_runtime_state,
    load_session_guard,
    now_iso,
    parse_guard_command,
    save_runtime_state,
    save_session_guard,
)


def _response(reason: str) -> int:
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


def _preview(text: str, limit: int = 120) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def main() -> int:
    payload = json.load(sys.stdin)
    prompt = payload.get("prompt", "")
    session_id = payload["session_id"]
    cwd = payload["cwd"]

    cleanup_old_runtime_files()
    command = parse_guard_command(prompt)
    if command is None:
        return 0

    ensure_guard_dirs()
    action = command["action"]
    if action == "show":
        config = load_session_guard(session_id)
        runtime = load_runtime_state(session_id) if config else None
        return _response(guard_summary(config, runtime))

    if action == "off":
        clear_guard_files(
            session_id,
            remove_session=True,
            remove_runtime=True,
            remove_success=True,
        )
        return _response("Guard disabled.")

    config_data = command["config"]
    guard_record = build_guard_record(session_id, cwd, config_data)
    save_session_guard(session_id, guard_record)
    runtime = load_runtime_state(session_id)
    runtime.update(
        {
            "version": 1,
            "session_id": session_id,
            "attempts": 0,
            "last_turn_id": payload.get("turn_id"),
            "last_checked_at": now_iso(),
            "last_assistant_message_preview": None,
            "last_match_ok": False,
            "last_match_capture": None,
            "exhausted": False,
        }
    )
    save_runtime_state(session_id, runtime)
    return _response(
        "Guard set."
        f" prompt={_preview(guard_record['goal_check_prompt'])}"
        f" template={guard_record['success_template_for_agent']}"
        f" regex={guard_record['success_regex']}"
        f" auto_clear={str(guard_record['auto_clear_on_success']).lower()}"
        f" notify={str(guard_record['notify_on_success']).lower()}"
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GuardError as exc:
        print(
            json.dumps(
                {"decision": "block", "reason": f"Guard configuration error: {exc}"},
                ensure_ascii=False,
            )
        )
        raise SystemExit(0)
    except Exception as exc:
        print(
            json.dumps(
                {"decision": "block", "reason": f"Guard internal error: {exc}"},
                ensure_ascii=False,
            )
        )
        raise SystemExit(0)
