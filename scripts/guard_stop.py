#!/usr/bin/env python3
import json
import sys

from guard_common import (
    build_continue_prompt,
    cleanup_old_runtime_files,
    clear_guard_files,
    load_runtime_state,
    load_session_guard,
    match_success,
    now_iso,
    save_runtime_state,
    save_success_marker,
)


def main() -> int:
    payload = json.load(sys.stdin)
    session_id = payload["session_id"]
    turn_id = payload["turn_id"]
    final_text = payload.get("last_assistant_message")

    cleanup_old_runtime_files()
    config = load_session_guard(session_id)
    if not config or not config.get("enabled", True):
        return 0

    runtime = load_runtime_state(session_id)
    text_preview = (final_text or "").strip()
    if len(text_preview) > 240:
        text_preview = text_preview[:239].rstrip() + "..."

    matched, capture = match_success(config, final_text)
    runtime.update(
        {
            "last_turn_id": turn_id,
            "last_checked_at": now_iso(),
            "last_assistant_message_preview": text_preview or None,
            "last_match_ok": matched,
            "last_match_capture": capture,
        }
    )

    if matched:
        save_success_marker(
            session_id,
            {
                "version": 1,
                "session_id": session_id,
                "turn_id": turn_id,
                "cwd": payload["cwd"],
                "succeeded_at": now_iso(),
                "goal_check_prompt": config["goal_check_prompt"],
                "success_template_for_agent": config["success_template_for_agent"],
                "full_final_text": (final_text or "").strip(),
                "completion_summary": capture or "",
                "notify_on_success": config.get("notify_on_success", True),
            },
        )
        if config.get("auto_clear_on_success", True):
            clear_guard_files(
                session_id,
                remove_session=True,
                remove_runtime=True,
                remove_success=False,
            )
        else:
            runtime["attempts"] = 0
            runtime["exhausted"] = False
            save_runtime_state(session_id, runtime)
        return 0

    attempts = int(runtime.get("attempts", 0)) + 1
    runtime["attempts"] = attempts
    exhausted = attempts > int(config.get("max_auto_continue", 20))
    runtime["exhausted"] = exhausted
    save_runtime_state(session_id, runtime)

    if exhausted:
        return 0

    print(
        json.dumps(
            {
                "decision": "block",
                "reason": build_continue_prompt(config),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
