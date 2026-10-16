import json
import pytest
from aie.planning import build_plan_messages, validate_plan_output


def test_plan_messages_are_untrusted_and_not_saved():
    messages = build_plan_messages({"title": "Improve observer", "description": ""})
    assert "untrusted data" in messages[0]["content"]
    assert "will not be saved or run" in messages[0]["content"]


def test_plan_dependencies_must_point_backward():
    good = {"steps": [
        {"title": "Inspect", "description": "", "depends_on": []},
        {"title": "Implement", "description": "", "depends_on": [0]},
    ]}
    assert validate_plan_output(json.dumps(good))["saved"] is False
    bad = {"steps": [{"title": "A", "description": "", "depends_on": [0]}]}
    with pytest.raises(ValueError):
        validate_plan_output(json.dumps(bad))


def test_plan_rejects_extra_fields_and_empty_steps():
    with pytest.raises(ValueError):
        validate_plan_output(json.dumps({"steps": [], "extra": True}))
