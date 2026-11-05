"""Deterministic answers for APEX identity and live capability questions."""
from __future__ import annotations

import re
from typing import Any


def classify(query: str) -> str | None:
    text = re.sub(r"[^a-z0-9 ]+", " ", query.casefold())
    text = " ".join(text.split())
    if not text:
        return None
    if "process" in text and any(word in text for word in ("see", "show", "list", "inspect", "running", "view")):
        return "process_visibility"
    if any(phrase in text for phrase in ("who made you", "who created you", "your creator", "who built you", "who developed you")):
        return "creator"
    if any(phrase in text for phrase in ("what model", "which model", "what powers you", "foundation model", "model are you using")):
        return "model"
    if any(phrase in text for phrase in ("what can you do", "your capabilities", "what tools", "which tools", "what are you connected to")):
        return "capabilities"
    if any(phrase in text for phrase in ("who are you", "what are you", "your name", "introduce yourself")):
        return "identity"
    if any(phrase in text for phrase in ("what is my name", "who am i", "do you know my name")):
        return "user_identity"
    return None


def answer(kind: str, *, manifest: dict[str, Any], profile: dict[str, Any],
           operator_name: str | None = None) -> str:
    model = manifest.get("foundation_model") or {}
    tag = manifest.get("resolved_model_tag") or manifest.get("foundation_model_tag") or "unknown"
    family = model.get("family") or "unknown"
    size = model.get("parameter_size") or "unknown"
    quant = model.get("quantization_level") or "unknown"
    if kind == "identity":
        return ("I'm APEX, your independent local-first Windows assistant, sir. "
                "My personality and runtime are APEX-owned; the model underneath is reported by my live host manifest.")
    if kind == "creator":
        if operator_name:
            return f"My configured operator/creator attribution is {operator_name}, sir. My foundation model is a separate component."
        return ("My runtime does not contain an explicit creator/operator attribution, sir, so I won't invent one. "
                "I'm APEX, an independently configured assistant; my foundation model and Ollama provider are separate components.")
    if kind == "model":
        if manifest.get("ollama_status") != "connected" or not manifest.get("model_installed"):
            return ("I can't verify the configured foundation model right now, sir. "
                    "My local Ollama provider or the configured model tag is unavailable.")
        details = f"{family}, {size}, {quant}" if family != "unknown" or size != "unknown" else "model family metadata unavailable"
        return (f"I'm running the configured Ollama model tag {tag} ({details}), sir. "
                "Inference is local over the loopback API, with think=False in the Python request.")
    if kind == "capabilities":
        providers = manifest.get("providers", [])
        available = [item.get("name", "") for item in providers if item.get("available")]
        unavailable = [item.get("name", "") for item in providers if not item.get("available")]
        groups = []
        checks = {
            "Windows diagnostics": ("apex_get_system_summary", "apex_list_processes", "apex_get_network_summary"),
            "Desktop/window automation": ("apex_list_windows", "apex_activate_window", "apex_mouse_click"),
            "UI Automation": ("apex_inspect_uia", "apex_uia_invoke", "apex_type_text"),
            "Applications": ("apex_discover_applications", "apex_launch_application"),
            "Files and clipboard": ("apex_list_directory", "apex_copy_file", "apex_get_clipboard_text"),
            "Audio/display": ("apex_get_master_volume", "apex_set_master_volume", "apex_get_brightness"),
            "Network/services/tasks": ("apex_list_network_configurations", "apex_set_dns_servers", "apex_list_services"),
        }
        for label, required in checks.items():
            if any(name in available for name in required):
                groups.append(label)
        unavailable_count = len(unavailable)
        summary = ", ".join(groups) if groups else "No Windows action providers are currently available"
        return (f"My live manifest currently reports {len(available)} available tools across: {summary}. "
                f"{unavailable_count} registered tools are unavailable. Mutating actions require host approval; "
                "I do not have unrestricted shell, kernel or administrator access.")
    if kind == "user_identity":
        display_name = profile.get("display_name")
        if display_name:
            return f"Your configured profile name is {display_name}, sir."
        return "Your display name has not been configured in my APEX profile, sir. I won't infer it from Windows paths."
    return "I can't determine that from my current APEX host metadata."
