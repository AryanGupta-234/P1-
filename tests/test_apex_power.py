import uuid

from apex.windows.power import _guid_text, _to_guid


def test_power_scheme_guid_round_trips_without_reordering_bytes():
    expected = "381b4222-f694-41f0-9685-ff5bb260df2e"
    assert _guid_text(_to_guid(expected)) == expected


def test_power_scheme_guid_rejects_invalid_values():
    for value in ("", "default", "00000000-0000-0000-0000-000000000000x"):
        try:
            _to_guid(value)
        except ValueError:
            continue
        raise AssertionError(f"invalid power GUID was accepted: {value!r}")


def test_power_scheme_guid_accepts_standard_uuid_objects():
    value = uuid.uuid4()
    assert _guid_text(_to_guid(str(value))) == str(value)
