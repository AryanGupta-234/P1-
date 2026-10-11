# ADR-0005: Metadata-Only Windows Event Log Observation

- **Status:** Accepted
- **Date:** 2026-10-11

## Context
Windows Application/System logs can provide useful evidence about application and operating-system faults. Event descriptions and XML payloads can contain user or system details, so reading full messages would create unnecessary collection risk.

## Decision
- Event Log collection is disabled by default and must be explicitly enabled.
- Only classic Application and System logs are allowed; Security and arbitrary channels are excluded.
- The first poll establishes a record cursor and does not replay historical events.
- Store only provider name, channel, record number, event ID/type/category, computer name and generated timestamp.
- Do not read message text, XML data or insertion strings.
- Bound records per poll and polling cadence; handle log clear/rollover.
- Access errors are reported as metadata-only health events, without raw error messages.
- Hosted CI uses a fake Event Log API; target-desktop permissions and behavior still require validation.

## Consequences
This provides structured fault evidence without collecting full Event Log messages. It does not replace ETW, and the classic Application/System API has different coverage from newer analytic/debug channels.
