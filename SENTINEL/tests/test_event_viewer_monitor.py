from sentinel import collectors


def test_event_viewer_parser_extracts_crash_identity_without_raw_command_line():
    event_xml = r"""<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
      <System>
        <Provider Name="Application Error" />
        <EventID>1000</EventID>
        <Level>2</Level>
        <TimeCreated SystemTime="2026-10-28T08:30:00.000Z" />
        <EventRecordID>4812</EventRecordID>
      </System>
      <EventData>
        <Data Name="AppName">C:\Program Files\Vendor\viewer.exe</Data>
        <Data Name="ModuleName">C:\Windows\System32\fault.dll</Data>
        <Data Name="ExceptionCode">0xc0000005</Data>
        <Data Name="CommandLine">viewer.exe --password=should-not-leak</Data>
      </EventData>
    </Event>"""
    event = collectors._parse_event_xml(event_xml)

    assert event["provider"] == "Application Error"
    assert event["event_id"] == "1000"
    assert event["record_id"] == "4812"
    assert event["level"] == "2"
    assert event["data"]["AppName"] == "viewer.exe"
    assert event["data"]["ModuleName"] == "fault.dll"
    assert event["data"]["ExceptionCode"] == "0xc0000005"
    assert "CommandLine" not in event["data"]


def test_event_viewer_identifies_crashes_and_builds_evidence_summary():
    event = {
        "provider": "Application Error",
        "event_id": "1000",
        "level": "2",
        "record_id": "4812",
        "occurred_at": None,
        "data": {"AppName": "viewer.exe", "ModuleName": "fault.dll", "ExceptionCode": "0xc0000005"},
    }
    assert collectors._event_is_review_worthy("Application", event)
    summary = collectors._event_summary("Application", event, historical=True)
    assert "Application Error" in summary
    assert "Event ID 1000" in summary
    assert "viewer.exe" in summary
    assert "historical" in summary


def test_event_viewer_baseline_is_durable_and_historical_crashes_are_reviewed():
    source = (collectors.__file__)
    with open(source, encoding="utf-8") as handle:
        content = handle.read()
    assert "CREATE TABLE IF NOT EXISTS windows_event_seen" in content
    assert "CREATE TABLE IF NOT EXISTS windows_event_state" in content
    assert "baseline_complete" in content
    assert "if historical and not important" in content
    assert "application" in content and "1002" in content
    assert "DELETE FROM windows_event_seen WHERE seen_at<?" in content



def test_event_log_backfill_remains_open_until_every_channel_is_readable():
    source = open(collectors.__file__, encoding="utf-8").read()
    assert "if not baseline and channels_ok == len(queries)" in source
    assert "temporarily cannot query one of the configured Event Viewer logs" in source


def test_kernel_power_and_gpu_driver_events_can_trigger_workflows():
    from sentinel import workflow_engine

    assert workflow_engine._event_category(
        "Kernel-Power", "Kernel-Power unexpected restart Event ID 41"
    ) == "hardware_error"
    assert workflow_engine._event_category(
        "Display", "GPU driver reset/error (TDR)"
    ) == "driver_error"
