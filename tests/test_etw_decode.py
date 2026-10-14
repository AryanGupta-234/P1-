from pathlib import Path

from aie.providers.etw_decode import decode_trace_xml, iter_process_events
from aie.store import EventStore


def _write_xml(path: Path):
    path.write_text("""<?xml version="1.0"?>
<Events xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <Event><System>
    <Provider Name="Microsoft-Windows-Kernel-Process" Guid="{22FB2CD6-0E7B-422B-A0C7-2FAD1FD0E716}"/>
    <EventID>1</EventID><TimeCreated SystemTime="2026-10-14T10:00:00.000Z"/>
  </System><EventData>
    <Data Name="ProcessID">4242</Data><Data Name="ParentProcessID">100</Data>
    <Data Name="ImageName">C:\\Program Files\\Demo\\demo.exe</Data>
    <Data Name="CommandLine">must-not-be-retained --secret</Data>
  </EventData></Event>
  <Event><System>
    <Provider Name="Microsoft-Windows-Kernel-Process" Guid="{22FB2CD6-0E7B-422B-A0C7-2FAD1FD0E716}"/>
    <EventID>2</EventID><TimeCreated SystemTime="2026-10-14T10:00:05.000Z"/>
  </System><EventData><Data Name="ProcessID">4242</Data></EventData></Event>
  <Event><System>
    <Provider Name="Other" Guid="{00000000-0000-0000-0000-000000000000}"/>
    <EventID>1</EventID><TimeCreated SystemTime="2026-10-14T10:00:06.000Z"/>
  </System><EventData><Data Name="ProcessID">9</Data></EventData></Event>
</Events>""", encoding="utf-8")


def test_etw_xml_parser_normalizes_only_kernel_process_start_stop(tmp_path):
    source = tmp_path / "trace.xml"
    _write_xml(source)
    events = list(iter_process_events(source, event_host_id="host-test"))

    assert [event.event_type for event in events] == [
        "process.started_etw", "process.stopped_etw"
    ]
    assert events[0].entity.name == "demo.exe"
    assert events[0].entity.stable_id == "4242"
    assert events[0].data == {"pid": 4242, "parent_pid": 100, "image_name": "demo.exe"}
    assert events[0].host_id == "host-test"
    assert "CommandLine" not in str(events[0].data)
    assert events[0].evidence_kind == "observed"


def test_etw_xml_decoder_streams_jsonl(tmp_path):
    source = tmp_path / "trace.xml"
    output = tmp_path / "out" / "events.jsonl"
    _write_xml(source)
    assert decode_trace_xml(source, output, event_host_id="test") == 2
    assert len(output.read_text(encoding="utf-8").splitlines()) == 2


def test_etw_xml_decoder_refuses_input_overwrite(tmp_path):
    source = tmp_path / "trace.xml"
    _write_xml(source)
    try:
        decode_trace_xml(source, source)
    except ValueError as exc:
        assert "must not overwrite" in str(exc)
    else:
        raise AssertionError("expected output/input collision to be rejected")


def test_etw_xml_decoder_refuses_to_overwrite_existing_output(tmp_path):
    source = tmp_path / "trace.xml"
    output = tmp_path / "events.jsonl"
    _write_xml(source)
    output.write_text("keep", encoding="utf-8")
    try:
        decode_trace_xml(source, output)
    except FileExistsError:
        pass
    else:
        raise AssertionError("expected existing output to be protected")
    assert output.read_text(encoding="utf-8") == "keep"


def test_etw_xml_decoder_rejects_malformed_xml(tmp_path):
    source = tmp_path / "broken.xml"
    source.write_text("<Events><Event>", encoding="utf-8")
    try:
        list(iter_process_events(source, event_host_id="test"))
    except Exception as exc:
        import xml.etree.ElementTree as ET
        assert isinstance(exc, ET.ParseError)
    else:
        raise AssertionError("expected malformed XML to fail")


def test_etw_import_is_idempotent_across_repeated_decodes(tmp_path):
    source = tmp_path / "trace.xml"
    _write_xml(source)
    store = EventStore(tmp_path / "events.sqlite3")
    decode_trace_xml(source, tmp_path / "first.jsonl", event_host_id="stable-host", store=store)
    decode_trace_xml(source, tmp_path / "second.jsonl", event_host_id="stable-host", store=store)
    assert store.count() == 2
