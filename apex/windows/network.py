"""WMI-backed network configuration inspection and DNS changes with read-back verification."""
from __future__ import annotations
import ipaddress
import os
from typing import Any

def _service():
    if os.name != "nt":
        raise OSError("Windows network configuration requires Windows")
    try:
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for Windows network configuration") from exc
    locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
    return locator.ConnectServer(".", "root\\cimv2")

def list_configurations(limit: int = 100) -> dict[str, Any]:
    if isinstance(limit, bool) or not 1 <= limit <= 300:
        raise ValueError("limit must be between 1 and 300")
    service = _service()
    query = ("SELECT Index, Description, MACAddress, IPAddress, IPSubnet, DefaultIPGateway, "
             "DNSServerSearchOrder, DHCPEnabled, DHCPServer, IPConnectionMetric "
             "FROM Win32_NetworkAdapterConfiguration WHERE IPEnabled=True")
    rows = []
    for item in service.ExecQuery(query):
        rows.append({"index": int(item.Index), "description": str(item.Description or "")[:240],
            "mac_address": str(item.MACAddress or "")[:40],
            "ip_addresses": [str(x) for x in (item.IPAddress or [])[:8]],
            "subnets": [str(x) for x in (item.IPSubnet or [])[:8]],
            "gateways": [str(x) for x in (item.DefaultIPGateway or [])[:8]],
            "dns_servers": [str(x) for x in (item.DNSServerSearchOrder or [])[:8]],
            "dhcp_enabled": bool(item.DHCPEnabled), "dhcp_server": str(item.DHCPServer or "")[:64],
            "metric": int(item.IPConnectionMetric) if item.IPConnectionMetric is not None else None})
        if len(rows) >= limit:
            break
    return {"adapters": rows, "count": len(rows), "source": "WMI Win32_NetworkAdapterConfiguration"}

def set_dns_servers(adapter_index: int, dns_servers: list[str]) -> dict[str, Any]:
    if isinstance(adapter_index, bool) or not isinstance(adapter_index, int) or adapter_index < 0:
        raise ValueError("adapter_index must be a non-negative integer")
    if not isinstance(dns_servers, list) or not 1 <= len(dns_servers) <= 4:
        raise ValueError("provide between one and four DNS server IP addresses")
    validated = []
    for address in dns_servers:
        try:
            validated.append(str(ipaddress.ip_address(address)))
        except ValueError as exc:
            raise ValueError(f"invalid DNS address: {address!r}") from exc
    service = _service()
    matches = list(service.ExecQuery(
        f"SELECT Index, DNSServerSearchOrder FROM Win32_NetworkAdapterConfiguration WHERE Index={adapter_index} AND IPEnabled=True"))
    if len(matches) != 1:
        raise ValueError("network adapter index is missing or ambiguous")
    adapter = matches[0]
    previous = [str(x) for x in (adapter.DNSServerSearchOrder or [])]
    params = adapter.Methods_("SetDNSServerSearchOrder").InParameters.SpawnInstance_()
    params.DNSServerSearchOrder = validated
    result = adapter.ExecMethod_("SetDNSServerSearchOrder", params)
    if int(result.ReturnValue) not in {0, 1}:
        raise OSError(f"Windows DNS configuration returned WMI code {int(result.ReturnValue)}")
    refreshed = list(service.ExecQuery(
        f"SELECT Index, DNSServerSearchOrder FROM Win32_NetworkAdapterConfiguration WHERE Index={adapter_index} AND IPEnabled=True"))
    observed = [str(x) for x in (refreshed[0].DNSServerSearchOrder or [])] if len(refreshed) == 1 else []
    if observed != validated:
        rollback = adapter.Methods_("SetDNSServerSearchOrder").InParameters.SpawnInstance_()
        rollback.DNSServerSearchOrder = previous or None
        adapter.ExecMethod_("SetDNSServerSearchOrder", rollback)
        raise RuntimeError("DNS postcondition failed; previous DNS configuration was restored where possible")
    return {"summary": f"Updated DNS servers for adapter {adapter_index}.", "adapter_index": adapter_index,
            "previous_dns_servers": previous, "dns_servers": observed, "verified": True}

def provider_available() -> bool:
    if os.name != "nt":
        return False
    try:
        import win32com.client
        return True
    except ImportError:
        return False


def set_adapter_enabled(adapter_index: int, enabled: bool) -> dict[str, Any]:
    """Enable/disable one exact network adapter; this may disconnect the current session."""
    if isinstance(adapter_index, bool) or not isinstance(adapter_index, int) or adapter_index < 0:
        raise ValueError("adapter_index must be a non-negative integer")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    service = _service()
    matches = list(service.ExecQuery(
        f"SELECT Index, Name, NetEnabled FROM Win32_NetworkAdapter WHERE Index={adapter_index}"
    ))
    if len(matches) != 1:
        raise LookupError("network adapter index is missing or ambiguous")
    adapter = matches[0]
    previous = bool(adapter.NetEnabled) if adapter.NetEnabled is not None else None
    method_name = "Enable" if enabled else "Disable"
    if previous is enabled:
        return {"summary": f"Network adapter {adapter_index} is already {'enabled' if enabled else 'disabled'}.",
                "adapter_index": adapter_index, "enabled": enabled, "verified": True}
    result = adapter.ExecMethod_(method_name)
    return_code = int(result.ReturnValue)
    if return_code not in {0, 1}:
        raise OSError(f"Windows adapter {method_name} returned WMI code {return_code}")
    refreshed = list(service.ExecQuery(
        f"SELECT Index, Name, NetEnabled FROM Win32_NetworkAdapter WHERE Index={adapter_index}"
    ))
    observed = bool(refreshed[0].NetEnabled) if len(refreshed) == 1 and refreshed[0].NetEnabled is not None else None
    if observed is not enabled:
        raise RuntimeError("network adapter state did not reach requested postcondition")
    return {"summary": f"Network adapter {adapter_index} is now {'enabled' if enabled else 'disabled'}.",
            "adapter_index": adapter_index, "adapter_name": str(adapter.Name or "")[:240],
            "previous_enabled": previous, "enabled": observed, "verified": True}


def dhcp_lease(adapter_index: int, action: str) -> dict[str, Any]:
    if isinstance(adapter_index, bool) or not isinstance(adapter_index, int) or adapter_index < 0:
        raise ValueError("adapter_index must be a non-negative integer")
    methods = {"renew": "RenewDHCPLease", "release": "ReleaseDHCPLease"}
    if action not in methods:
        raise ValueError("action must be renew or release")
    service = _service()
    matches = list(service.ExecQuery(
        f"SELECT Index, DHCPEnabled FROM Win32_NetworkAdapterConfiguration WHERE Index={adapter_index} AND IPEnabled=True"
    ))
    if len(matches) != 1:
        raise LookupError("IP-enabled adapter configuration was not found")
    adapter = matches[0]
    if not bool(adapter.DHCPEnabled):
        raise ValueError("DHCP lease action is unavailable on a statically configured adapter")
    result = adapter.ExecMethod_(methods[action])
    code = int(result.ReturnValue)
    if code not in {0, 1}:
        raise OSError(f"Windows DHCP {action} returned WMI code {code}")
    return {"summary": f"Requested DHCP lease {action} for adapter {adapter_index}.",
            "adapter_index": adapter_index, "return_code": code, "verified": False,
            "verification": "Re-read adapter IP/gateway/DHCP state after the lease operation completes."}
