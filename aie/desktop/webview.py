"""Python/pywebview desktop dashboard for the AIE local runtime."""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path
from typing import Any

class DashboardError(RuntimeError):
    """A local dashboard operation failed."""

class DashboardApi:
    """Narrow, allow-listed bridge between the web UI and local AIE commands."""
    def __init__(self, runner=None) -> None:
        self._runner = runner or subprocess.run

    def _run(self, *args: str, timeout: float = 12.0) -> dict[str, Any]:
        try:
            result = self._runner(
                [sys.executable, "-m", "aie.cli", *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "command": "aie " + " ".join(args),
                    "output": f"{type(exc).__name__}: {exc}", "exit_code": -1}
        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        return {"ok": result.returncode == 0, "command": "aie " + " ".join(args),
                "output": output or error or ("Completed." if result.returncode == 0 else "Command failed."),
                "exit_code": result.returncode}

    def _json_command(self, *args: str, timeout: float = 12.0):
        result = self._run(*args, timeout=timeout)
        if not result["ok"]:
            return None, result
        try:
            value = json.loads(result["output"])
        except (TypeError, ValueError):
            return None, {**result, "ok": False, "output": "AIE returned invalid JSON."}
        if not isinstance(value, dict):
            return None, {**result, "ok": False, "output": "AIE returned an unexpected data shape."}
        return value, result

    def refresh(self) -> dict[str, Any]:
        """Collect bounded local status; never starts observers or network probes."""
        from datetime import datetime
        commands = {
            "status": self._run("status"),
            "health": self._run("health"),
            "retention": self._run("retention-status"),
            "tasks": self._run("task", "list", "--limit", "40"),
            "memory": self._run("memory-conflicts"),
            "permissions": self._run("capability-permissions"),
        }
        video, video_result = self._json_command(
            "video-dashboard", "--json", "--lookback-hours", "24", "--limit", "500", timeout=8.0
        )
        commands["video"] = video_result
        return {
            "ok": True, "generated_at": datetime.now().astimezone().isoformat(),
            "commands": commands, "video": video,
            "observer_paused": "paused" in commands["status"]["output"].lower(),
            "errors": [{"command": key, "message": value["output"]}
                       for key, value in commands.items() if not value["ok"]],
        }

    def action(self, name: str, value: str = "") -> dict[str, Any]:
        """Run only named, reviewed AIE actions; never execute arbitrary shell input."""
        if name == "pause": return self._run("pause")
        if name == "resume": return self._run("resume")
        if name == "evaluate": return self._run("video-evaluate", timeout=30.0)
        if name == "advice":
            if value not in {"routine", "complex"}:
                return {"ok": False, "output": "Choose routine or complex reasoning."}
            return self._run("video-advice", "--tier", value, timeout=150.0)
        if name == "tasks": return self._run("task", "list", "--limit", "100")
        if name == "health": return self._run("health")
        if name == "memory": return self._run("memory-conflicts")
        if name == "permissions": return self._run("capability-permissions")
        if name == "notifications": return self._run("notifications-status")
        if name == "retention": return self._run("retention-status")
        return {"ok": False, "output": "This dashboard action is not allow-listed."}

def launch_dashboard() -> None:
    """Open the native WebView window."""
    try:
        import webview
    except ImportError as exc:
        raise DashboardError("pywebview is missing. Run .\\scripts\\start-dashboard.ps1.") from exc
    asset = Path(__file__).with_name("web") / "index.html"
    if not asset.is_file():
        raise DashboardError(f"Dashboard UI asset is missing: {asset}")
    webview.create_window(
        "P1 — Autonomous Intelligence Ecosystem", asset.resolve().as_uri(),
        js_api=DashboardApi(), width=1540, height=980, min_size=(1120, 720),
        background_color="#0b1020", text_select=True,
    )
    webview.start(debug=False, http_server=False)
