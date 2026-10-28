from sentinel import component_intelligence, core, launch_provenance


def _win_normalize(value):
    raw = str(value or "").strip().strip('"').replace("/", "\\")
    return raw.casefold() if raw.lower().startswith("c:\\") else ""


def test_launch_identities_are_stable_hashes_not_paths():
    startup = launch_provenance.startup_component_id("Registry · Current user", "VendorTray")
    task = launch_provenance.task_component_id(r"\Vendor\Maintenance", "VendorUpdater")
    binary = launch_provenance.binary_component_id(r"C:\Program Files\Vendor\Updater.exe")

    assert startup == launch_provenance.startup_component_id("Registry · Current user", "VendorTray")
    assert startup.startswith("startup:")
    assert task.startswith("task:")
    assert binary.startswith("binary:")
    for value in (startup, task, binary):
        assert r"C:\Program Files" not in value
        assert "Maintenance" not in value


def test_launch_target_parser_discards_arguments_and_classifies_wrapper(monkeypatch):
    monkeypatch.setattr(launch_provenance, "_normal_path", _win_normalize)
    target = launch_provenance._extract_launch_target(
        '"C:\\Program Files\\Vendor\\agent.exe" --profile private-user --token=secret-value'
    )
    assert target == {
        "binary_path": r"c:\program files\vendor\agent.exe",
        "binary_name": "agent.exe",
        "launch_kind": "direct_executable",
        "has_arguments": True,
    }
    assert "private-user" not in str(target)
    assert "secret-value" not in str(target)

    wrapper = launch_provenance._extract_launch_target(
        r"C:\Windows\System32\cmd.exe /c vendor.exe"
    )
    assert wrapper["launch_kind"] == "command_host"
    assert wrapper["has_arguments"] is True


def test_startup_task_graph_uses_exact_binary_app_and_service_relationships(monkeypatch):
    monkeypatch.setattr(launch_provenance, "_normal_path", _win_normalize)
    monkeypatch.setattr(launch_provenance, "_path_under", lambda path, root:
                        bool(path and root and path.startswith(root.rstrip("\\") + "\\")))
    monkeypatch.setattr(launch_provenance, "_protected_process", lambda *_args: False)

    snapshot = {
        "startup": [{
            "name": "VendorTray", "source": "Registry · Current user",
            "binary_path": r"C:\Program Files\Vendor\Agent.exe",
            "has_arguments": True, "enabled": True,
        }],
        "tasks": [{
            "name": "VendorUpdater", "task_path": r"\Vendor\Maintenance",
            "state": "Ready", "enabled": True, "run_level": "HighestAvailable",
            "logon_type": "Interactive", "actions": [
                {"binary_path": r"C:\Program Files\Vendor\Updater.exe",
                 "action_kind": "Exec", "has_arguments": True},
                {"binary_path": "", "action_kind": "ComHandler", "has_arguments": False},
            ],
        }],
        "startup_complete": True, "tasks_complete": True,
        "apps_complete": True, "service_graph_complete": True,
    }
    service_rows = [{
        "name": "VendorAgentSvc",
        "binary_path": r"C:\Program Files\Vendor\Agent.exe",
    }]
    apps = [{
        "name": "Vendor Suite", "publisher": "Vendor Ltd.", "version": "4.2",
        "location": r"C:\Program Files\Vendor",
    }]

    graph = launch_provenance._build_graph(snapshot, service_rows, apps, now=1700000000.0)
    relations = {(edge[0], edge[1], edge[2], edge[3]) for edge in graph["relationships"]}
    startup_id = launch_provenance.startup_component_id("Registry · Current user", "VendorTray")
    task_id = launch_provenance.task_component_id(r"\Vendor\Maintenance", "VendorUpdater")
    agent_id = launch_provenance.binary_component_id(r"C:\Program Files\Vendor\Agent.exe")
    updater_id = launch_provenance.binary_component_id(r"C:\Program Files\Vendor\Updater.exe")
    app_id = launch_provenance.app_component_id("Vendor Suite", "Vendor Ltd.", "4.2")
    service_id = component_intelligence.service_component_id("VendorAgentSvc")

    assert (startup_id, agent_id, "launches_binary", "path_resolved") in relations
    assert (task_id, updater_id, "launches_binary", "path_resolved") in relations
    assert (agent_id, app_id, "installed_under_app", "unique_install_location_prefix") in relations
    assert (agent_id, service_id, "same_executable_as_service", "exact_executable_path") in relations

    stored = str({
        "catalog": graph["catalog_rows"],
        "metadata": graph["metadata_rows"],
        "relationships": graph["relationships"],
    })
    for private in (r"C:\Program Files", "private-user", "--profile", "secret-value",
                    "task_path", "logon_type"):
        assert private not in stored
    assert '"has_arguments":true' in stored


def test_ambiguous_application_install_paths_are_not_guessed(monkeypatch):
    monkeypatch.setattr(launch_provenance, "_normal_path", _win_normalize)
    monkeypatch.setattr(launch_provenance, "_path_under", lambda path, root:
                        bool(path and root and path.startswith(root.rstrip("\\") + "\\")))
    snapshot = {
        "startup": [{
            "name": "SharedHelper", "source": "Registry · All users",
            "binary_path": r"C:\Program Files\Shared\Helper.exe", "has_arguments": False,
        }],
        "tasks": [], "startup_complete": True, "tasks_complete": True,
        "apps_complete": True, "service_graph_complete": True,
    }
    apps = [
        {"name": "Product A", "publisher": "A", "version": "1", "location": r"C:\Program Files\Shared"},
        {"name": "Product B", "publisher": "B", "version": "1", "location": r"C:\Program Files\Shared"},
    ]
    graph = launch_provenance._build_graph(snapshot, [], apps, now=1700000000.0)
    assert not any(edge[2] == "installed_under_app" for edge in graph["relationships"])


def test_microsoft_and_vanguard_scheduled_tasks_are_marked_protected(monkeypatch):
    monkeypatch.setattr(launch_provenance, "_normal_path", _win_normalize)
    monkeypatch.setattr(launch_provenance, "_protected_process", lambda *_args: False)
    snapshot = {
        "startup": [],
        "tasks": [
            {"name": "ScheduleDefrag", "task_path": r"\Microsoft\Windows\Defrag",
             "state": "Ready", "enabled": True, "actions": []},
            {"name": "VanguardTray", "task_path": r"\Riot\Vanguard",
             "state": "Ready", "enabled": True, "actions": []},
        ],
        "startup_complete": True, "tasks_complete": True,
        "apps_complete": True, "service_graph_complete": True,
    }
    graph = launch_provenance._build_graph(snapshot, [], [], now=1700000000.0)
    rows = {row[3]: bool(row[10]) for row in graph["catalog_rows"] if row[1] == "task"}
    assert rows["ScheduleDefrag"] is True
    assert rows["VanguardTray"] is True


def test_signature_queue_rotates_across_process_service_and_launch_binaries(monkeypatch):
    saved = {}
    monkeypatch.setattr(component_intelligence, "_load_state",
                        lambda _key: saved.get("rotation", {}))
    monkeypatch.setattr(component_intelligence, "_save_state",
                        lambda key, value: saved.update({key: value}))
    paths = {}
    for index in range(40):
        paths["process:" + str(index).zfill(3)] = "process-path-" + str(index)
    for index in range(24):
        paths["service:" + str(index).zfill(3)] = "service-path-" + str(index)
    for index in range(35):
        paths["binary:" + str(index).zfill(3)] = "launch-path-" + str(index)

    first = launch_provenance.select_signature_batch(paths, 28)
    second = launch_provenance.select_signature_batch(paths, 28)
    assert len(first) == len(second) == 28
    assert {key.split(":", 1)[0] for key, _value in first} == {"process", "service", "binary"}
    assert {key for key, _value in first} != {key for key, _value in second}


def test_durable_inventory_and_service_snapshots_exclude_commands_and_binary_paths():
    from pathlib import Path

    root = Path(launch_provenance.__file__).parents[1]
    inventory_source = (root / "inventory.py").read_text(encoding="utf-8")
    collectors_source = (root / "collectors.py").read_text(encoding="utf-8")

    assert 'durable["startup"]' in inventory_source
    assert 'durable["apps"]' in inventory_source
    assert 'durable["drivers"]' in inventory_source
    assert 'durable["services"]' in inventory_source
    assert "safe_service_rows" in collectors_source
    assert '"rows": safe_service_rows' in collectors_source
    assert '"binary_path": row.get("binary_path")' not in inventory_source
    assert 'persist_snapshot("services.latest", {"captured_at": time.time(), "summary": STATE["services"], "rows": cur' not in collectors_source
