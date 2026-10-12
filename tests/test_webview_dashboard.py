import json
from aie.desktop.webview import DashboardApi

class Result:
    def __init__(self, args, returncode=0):
        self.args=args; self.returncode=returncode; self.stdout=""; self.stderr=""

def test_refresh_collects_local_surfaces_and_video_json():
    calls=[]
    def runner(args, **kwargs):
        calls.append(args); result=Result(args)
        result.stdout=json.dumps({"schema_version":1,"overview":{"total_events_in_store":12},"events":[]}) if "video-dashboard" in args else "local output"
        return result
    payload=DashboardApi(runner=runner).refresh()
    assert payload["ok"] is True
    assert payload["video"]["overview"]["total_events_in_store"] == 12
    assert len(calls) == 7
    assert any("video-dashboard" in c for c in calls)
    assert any(c[-1] == "health" for c in calls)

def test_action_allowlist_rejects_arbitrary_commands():
    api=DashboardApi(runner=lambda *a,**k: Result(a[0]))
    result=api.action("powershell","Remove-Item")
    assert result["ok"] is False and "allow-listed" in result["output"]

def test_advisor_validates_tier_before_invoking_cli():
    calls=[]
    api=DashboardApi(runner=lambda args,**kwargs: calls.append(args) or Result(args))
    assert api.action("advice","remote")["ok"] is False
    assert calls == []

def test_commands_use_current_python_environment():
    api=DashboardApi(runner=lambda args,**kwargs: Result(args))
    assert api.action("health")["command"] == "aie health"
