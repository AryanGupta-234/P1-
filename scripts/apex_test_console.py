"""Temporary interactive smoke-test adapter for the APEX Python host.

This is not the Phase 6 desktop UI. Model inference remains direct Python-to-loopback
Ollama HTTP; this console exists only to exercise the Phase 1 host and approval path.
"""
from __future__ import annotations

import json

from apex import ApexService


def _confirm_action(tool_name: str, arguments: dict, risk: str) -> bool:
    print("\nAPEX ACTION REVIEW")
    print(f"Capability: {tool_name}")
    print(f"Risk tier:  {risk}")
    print("Arguments:")
    print(json.dumps(arguments, indent=2, ensure_ascii=False, default=str))
    answer = input("Approve this exact operation? [y/N]: ").strip().casefold()
    return answer in {"y", "yes"}


def main() -> int:
    service = ApexService(approval_handler=_confirm_action)
    try:
        manifest = service.start()
        print("APEX Phase 1 test console")
        print(f"Model: {manifest.get('resolved_model_tag') or manifest.get('foundation_model_tag')}")
        print(f"Ollama: {manifest.get('ollama_status')}")
        print(f"Database: {manifest.get('database_status')}")
        print("Mutations: approval-gated; emergency stop initially "
              f"{'ACTIVE' if manifest.get('policy', {}).get('emergency_stop') else 'inactive'}")
        print("Type /stop to disable all mutations, /resume to re-enable the approval-gated path, or /exit.")
        while True:
            try:
                user_text = input("\nYou > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nClosing APEX test console.")
                break
            if not user_text:
                continue
            command = user_text.casefold()
            if command in {"/exit", "/quit"}:
                break
            if command == "/stop":
                print(service.set_emergency_stop(True, reason="interactive_test_console"))
                continue
            if command == "/resume":
                confirmation = input("Re-enable approval-gated mutations? [y/N]: ").strip().casefold()
                if confirmation in {"y", "yes"}:
                    print(service.set_emergency_stop(False, reason="interactive_test_console"))
                else:
                    print("Emergency stop remains active.")
                continue
            try:
                result = service.send_message(user_text)
                print(f"APEX > {result.get('response', '')}")
                for event in result.get("tool_events", []):
                    print(f"  [{event.get('status')}] {event.get('tool')}: {event.get('summary')}")
            except Exception as exc:
                print(f"APEX runtime error: {type(exc).__name__}: {exc}")
        return 0
    finally:
        service.stop()


if __name__ == "__main__":
    raise SystemExit(main())
