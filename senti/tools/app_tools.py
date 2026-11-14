"""Application open/find/list/uninstall capabilities backed by dynamic Windows discovery."""
from __future__ import annotations

import os
from typing import Any

from senti.tools.registry import CapabilityRegistry, ToolDefinition
from senti.windows import launch, uninstall

UNINSTALL_COMPENSATION = "Not reversible automatically; reinstall from the original source."


def _object(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def _windows() -> bool:
    return os.name == "nt"


def _require_target(args: dict[str, Any]) -> None:
    if not str(args.get("application") or "").strip() and not str(args.get("entry_id") or "").strip():
        raise ValueError("provide 'application' (a name) or an exact 'entry_id'")


def register_app_tools(registry: CapabilityRegistry, store=None) -> None:
    """Register application listing, finding, launching and uninstall capabilities."""

    def list_software(args: dict[str, Any]) -> dict[str, Any]:
        return uninstall.list_installed_software(
            query=args.get("query"), kind=args.get("kind"), scope=args.get("scope"),
            publisher=args.get("publisher"), limit=args.get("limit", 100))

    def find_application(args: dict[str, Any]) -> dict[str, Any]:
        query = args["query"].strip()
        purpose = args.get("purpose", "both")
        limit = args.get("limit", 5)
        result: dict[str, Any] = {"query": query, "purpose": purpose}
        lines = []
        if purpose in {"open", "both"}:
            winner, ranked = launch.resolve_launch(query, store)
            result["open"] = {
                "resolved": launch.launch_candidate_dict(winner) if winner else None,
                "ambiguous": winner is None and bool(ranked),
                "candidates": [launch.launch_candidate_dict(c) for c in ranked[:limit]]}
            lines.append(f"open: {winner.item.display_name}" if winner
                         else f"open: {len(ranked)} candidate(s), none unambiguous")
        if purpose in {"uninstall", "both"}:
            entries, providers = uninstall.enumerate_software()
            resolution = uninstall.resolve_uninstall({"application": query}, entries)
            result["uninstall"] = {
                "resolved": resolution.entry.to_dict() if resolution.entry else None,
                "ambiguous": resolution.ambiguous,
                "candidates": [uninstall.candidate_dict(c) for c in resolution.candidates[:limit]],
                "providers": providers}
            lines.append(f"uninstall: {resolution.entry.display_name}" if resolution.entry
                         else f"uninstall: {len(resolution.candidates)} candidate(s), none unambiguous")
        result["summary"] = f"Application matches for '{query}' - " + "; ".join(lines)
        result["verified"] = True
        return result

    def simulate_uninstall(args: dict[str, Any]) -> dict[str, Any]:
        _require_target(args)
        return uninstall.simulate_uninstall(args)

    def run_uninstall(args: dict[str, Any]) -> dict[str, Any]:
        _require_target(args)
        return uninstall.uninstall(args)

    registry.register(ToolDefinition(
        name="senti_list_installed_software",
        description="List installed, uninstallable software (Win32/MSI from the Uninstall registry and current-user Store/MSIX packages) with name, publisher, version, size, kind and entry_id.",
        parameters=_object({
            "query": {"type": "string", "minLength": 1, "maxLength": 120},
            "kind": {"type": "string", "enum": ["any", "msi", "exe", "msix"]},
            "scope": {"type": "string", "enum": ["any", "machine", "user"]},
            "publisher": {"type": "string", "minLength": 1, "maxLength": 120},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500}}),
        risk="read_only", handler=list_software, available=_windows))
    registry.register(ToolDefinition(
        name="senti_find_application",
        description="Find an installed application by name for opening and/or uninstalling. Returns ranked candidates with scores and whether the match is unambiguous; use it before asking the user to choose.",
        parameters=_object({
            "query": {"type": "string", "minLength": 1, "maxLength": 120},
            "purpose": {"type": "string", "enum": ["open", "uninstall", "both"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ["query"]),
        risk="read_only", handler=find_application, available=_windows))
    registry.register(ToolDefinition(
        name="senti_launch_application",
        description="Open (launch) an installed application or Store app resolved by ranked name matching, then verify a process or window appeared. Ambiguous names return candidates instead of launching.",
        parameters=_object({
            "application": {"type": "string", "minLength": 1, "maxLength": 120},
            "verify_seconds": {"type": "integer", "minimum": 0, "maximum": 30}}, ["application"]),
        risk="controlled",
        handler=lambda args: launch.launch_application(args["application"], store=store,
                                                       verify_seconds=args.get("verify_seconds", 10)),
        simulate=lambda args: launch.simulate_launch(args, store=store),
        available=_windows))
    registry.register(ToolDefinition(
        name="senti_uninstall_application",
        description="Uninstall one installed application (MSI, EXE uninstaller or current-user Store/MSIX package) after preview and approval. Per-machine software shows the Windows UAC prompt. Pass entry_id from senti_find_application when names are ambiguous.",
        parameters=_object({
            "application": {"type": "string", "minLength": 1, "maxLength": 120},
            "entry_id": {"type": "string", "minLength": 5, "maxLength": 400},
            "quiet": {"type": "boolean"},
            "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 600}}),
        risk="high", handler=run_uninstall, simulate=simulate_uninstall,
        compensation=UNINSTALL_COMPENSATION, max_per_minute=2, available=_windows))
