from __future__ import annotations

import pytest

from aie.automation.uia_inspector import (
    UIAUnavailable,
    element_metadata,
    inspect_window,
    walk_element_tree,
)


class FakeInfo:
    def __init__(
        self,
        *,
        handle=None,
        process_id=123,
        control_type="Window",
        class_name="FakeWindow",
        automation_id="root",
        framework_id="WPF",
        enabled=True,
        visible=True,
    ):
        self.handle = handle
        self.process_id = process_id
        self.control_type = control_type
        self.class_name = class_name
        self.automation_id = automation_id
        self.framework_id = framework_id
        self.enabled = enabled
        self.visible = visible

    @property
    def name(self):
        raise AssertionError("UIA metadata inspection must not read UI text")

    @property
    def rich_text(self):
        raise AssertionError("UIA metadata inspection must not read rich text")


class FakeWrapper:
    def __init__(self, info=None, children=None, fail_children=False):
        self.element_info = info or FakeInfo()
        self._children = children or []
        self.fail_children = fail_children

    def children(self):
        if self.fail_children:
            raise RuntimeError("provider unavailable")
        return self._children


def test_element_metadata_omits_ui_text_properties():
    record = element_metadata(FakeInfo(handle=1001, process_id=55))
    assert record["handle"] == 1001
    assert record["process_id"] == 55
    assert record["control_type"] == "Window"
    assert "name" not in record
    assert "rich_text" not in record


def test_tree_walk_respects_depth_limit():
    leaf = FakeWrapper(FakeInfo(control_type="Button", automation_id="save"))
    child = FakeWrapper(FakeInfo(control_type="Pane"), [leaf])
    root = FakeWrapper(FakeInfo(), [child])

    result = walk_element_tree(root, max_depth=1, max_nodes=20)

    assert result["element_count"] == 2
    assert [item["depth"] for item in result["elements"]] == [0, 1]
    assert result["truncated"] is False


def test_tree_walk_respects_node_limit():
    root = FakeWrapper(FakeInfo(), [
        FakeWrapper(FakeInfo(control_type="Button", automation_id="one")),
        FakeWrapper(FakeInfo(control_type="Button", automation_id="two")),
        FakeWrapper(FakeInfo(control_type="Button", automation_id="three")),
    ])

    result = walk_element_tree(root, max_depth=4, max_nodes=2)

    assert result["element_count"] == 2
    assert result["truncated"] is True


def test_tree_walk_records_provider_failures_without_text():
    root = FakeWrapper(FakeInfo(), fail_children=True)
    result = walk_element_tree(root)

    assert result["element_count"] == 1
    assert result["traversal_errors"] == [
        {"depth": 0, "error_type": "RuntimeError"}
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_depth": -1},
        {"max_depth": 9},
        {"max_nodes": 0},
        {"max_nodes": 1001},
    ],
)
def test_tree_walk_rejects_unbounded_limits(kwargs):
    with pytest.raises(ValueError):
        walk_element_tree(FakeWrapper(), **kwargs)


def test_inspect_window_rejects_invalid_handles():
    for handle in (0, -1, "123"):
        with pytest.raises(ValueError):
            inspect_window(handle)

def test_live_backend_refuses_non_windows(monkeypatch):
    import aie.automation.uia_inspector as inspector

    monkeypatch.setattr(inspector.os, "name", "posix")
    with pytest.raises(UIAUnavailable):
        inspector.list_top_level_windows()
