"""Master output volume operations through Windows Core Audio (pycaw)."""
from __future__ import annotations
import os

def _endpoint():
    if os.name != "nt":
        raise OSError("Windows Core Audio is available only on Windows")
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError as exc:
        raise RuntimeError("pycaw is not installed in the APEX Windows environment") from exc
    return AudioUtilities.GetSpeakers().EndpointVolume

def get_master_volume() -> dict:
    endpoint = _endpoint()
    return {"volume_percent": round(float(endpoint.GetMasterVolumeLevelScalar()) * 100, 1),
            "muted": bool(endpoint.GetMute()), "source": "Windows Core Audio", "verified": True}

def set_master_volume(volume_percent: int) -> dict:
    if isinstance(volume_percent, bool) or not isinstance(volume_percent, int) or not 0 <= volume_percent <= 100:
        raise ValueError("volume_percent must be an integer from 0 through 100")
    endpoint = _endpoint()
    endpoint.SetMasterVolumeLevelScalar(volume_percent / 100.0, None)
    observed = round(float(endpoint.GetMasterVolumeLevelScalar()) * 100)
    if abs(observed - volume_percent) > 1:
        raise RuntimeError("Windows volume postcondition did not match the requested level")
    return {"summary": f"Master output volume is now {observed}%.", "volume_percent": observed, "verified": True}

def set_master_mute(muted: bool) -> dict:
    if not isinstance(muted, bool):
        raise ValueError("muted must be a boolean")
    endpoint = _endpoint()
    endpoint.SetMute(1 if muted else 0, None)
    observed = bool(endpoint.GetMute())
    if observed is not muted:
        raise RuntimeError("Windows mute postcondition did not match the requested state")
    return {"summary": "Master output muted." if observed else "Master output unmuted.",
            "muted": observed, "verified": True}

def provider_available() -> bool:
    if os.name != "nt":
        return False
    try:
        import pycaw.pycaw
        return True
    except ImportError:
        return False

def list_application_sessions() -> dict:
    if os.name != "nt":
        raise OSError("Windows audio sessions are available only on Windows")
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError as exc:
        raise RuntimeError("pycaw is not installed") from exc
    rows = []
    for session in AudioUtilities.GetAllSessions():
        try:
            process = session.Process
            if process is None:
                continue
            control = session.SimpleAudioVolume
            rows.append({"pid": int(process.pid), "process_name": process.name()[:180],
                         "volume_percent": round(float(control.GetMasterVolume()) * 100, 1),
                         "muted": bool(control.GetMute())})
        except Exception:
            continue
    return {"sessions": rows, "count": len(rows), "source": "Windows Core Audio sessions"}

def set_application_session_volume(pid: int, process_name: str, volume_percent: int) -> dict:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("pid must be a positive integer")
    if not isinstance(process_name, str) or not 1 <= len(process_name) <= 180:
        raise ValueError("process_name is required")
    if isinstance(volume_percent, bool) or not isinstance(volume_percent, int) or not 0 <= volume_percent <= 100:
        raise ValueError("volume_percent must be between 0 and 100")
    import psutil
    try:
        process = psutil.Process(pid)
        if process.name().casefold() != process_name.casefold():
            raise ValueError("PID no longer belongs to the named process")
        created = process.create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        raise ValueError("target process is no longer available") from exc
    from pycaw.pycaw import AudioUtilities
    matches = []
    for session in AudioUtilities.GetAllSessions():
        try:
            current = session.Process
            if current is not None and int(current.pid) == pid and current.name().casefold() == process_name.casefold():
                matches.append(session)
        except Exception:
            continue
    if len(matches) != 1:
        raise ValueError("audio session is missing or ambiguous for the target PID")
    matches[0].SimpleAudioVolume.SetMasterVolume(volume_percent / 100.0, None)
    observed = round(float(matches[0].SimpleAudioVolume.GetMasterVolume()) * 100)
    if abs(observed - volume_percent) > 1:
        raise RuntimeError("per-application volume postcondition failed")
    return {"summary": f"Set {process_name} audio session volume to {observed}%.", "pid": pid,
            "process_created_at": created, "volume_percent": observed, "verified": True}


def media_control(action: str) -> dict:
    """Dispatch a named Windows media key; does not inspect arbitrary app content."""
    import os
    if os.name != "nt":
        raise OSError("Windows media key support requires Windows")
    keys = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}
    if action not in keys:
        raise ValueError("media action must be play_pause, next, previous or stop")
    import ctypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    vk = keys[action]
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 0x0002, 0)
    return {"summary": f"Dispatched media action: {action}.", "action": action, "verified": False,
            "verification": "Media-key dispatch does not prove an application changed playback state."}
