from __future__ import annotations

from datetime import datetime

from .models import HostSection, ReportFacts


def build_report(client, start: datetime, end: datetime, report_type: str, cfg):
    del client

    generated_at = datetime.now(cfg.timezone).isoformat()
    scope_hosts = list(cfg.hosts)
    return ReportFacts(
        generated_at=generated_at,
        report_type=report_type,
        scope_start=start.isoformat(),
        scope_end=end.isoformat(),
        scope_timezone=str(cfg.timezone),
        scope_hosts=scope_hosts,
        source_base_url=cfg.base_url,
        coverage={"active_seconds": 0, "days": 1 if report_type == "day" else 0},
        combined=HostSection(
            active_seconds=0, afk_seconds=0, vim=None, input=None, apps=[], web=None
        ),
        per_host={
            host: HostSection(
                active_seconds=0, afk_seconds=0, vim=None, input=None, apps=[], web=None
            )
            for host in scope_hosts
        },
        notes=[],
    )
