from __future__ import annotations

import json
import sys
import tomllib
from datetime import date, datetime
from importlib import import_module
from pathlib import Path

import click

from . import __version__
from .aggregate import build_report
from .aw_client import AWClient, discover_host_buckets
from .config import Config, DEFAULT_CONFIG_PATHS, load_config
from .models import Dashboard, HostMeta, HostSnapshot
from .render_json import render_json
from .render_md import render_markdown
from .utils import day_range, parse_range

build_host_snapshot = import_module("aw_report.snapshot").build_host_snapshot

try:
    from .aggregate_dashboard import aggregate
except Exception:  # pragma: no cover - defensive import for partial repos
    aggregate = None

try:
    render_dashboard = import_module("aw_report.render_svg").render_dashboard
except Exception:  # pragma: no cover - defensive import for partial repos
    render_dashboard = None


def _resolve_config_path(config_path: Path | None) -> Path | None:
    if config_path and config_path.exists():
        return config_path
    for candidate in DEFAULT_CONFIG_PATHS:
        if candidate.exists():
            return candidate
    return config_path if config_path and config_path.exists() else None


def _load_raw_config(config_path: Path | None) -> dict:
    resolved = _resolve_config_path(config_path)
    if resolved is None:
        return {}
    with resolved.open("rb") as fh:
        return tomllib.load(fh)


def _load_host_meta(raw_config: dict, host_id: str) -> HostMeta | None:
    host_meta = raw_config.get("host_meta", {}).get(host_id)
    if not isinstance(host_meta, dict):
        return None
    label = host_meta.get("label")
    platform = host_meta.get("platform")
    if not isinstance(label, str) or not label.strip():
        return None
    if not isinstance(platform, str) or not platform.strip():
        return None
    return HostMeta(
        id=str(host_meta.get("id", host_id)),
        label=label,
        platform=platform,
    )


def _dump_snapshot(snapshot: HostSnapshot, output_path: Path | None) -> None:
    payload = snapshot.to_json()
    if output_path is None:
        click.echo(payload)
        return
    output_path.write_text(payload + "\n", encoding="utf-8")


@click.group()
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
@click.pass_context
def main(ctx: click.Context, config_path: Path | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["config"] = load_config(config_path)


@main.group()
def snapshot() -> None:
    """Generate HostSnapshot payloads."""


@snapshot.command("day")
@click.option(
    "--host",
    "host_id",
    required=True,
    help="Host config ID from aw-report.toml [host_meta.*]",
)
@click.option("--date", "date_str", default=None, help="YYYY-MM-DD, defaults to today")
@click.option("--out", "output_path", type=click.Path(path_type=Path), default=None)
@click.option("--skip-opencode", is_flag=True, default=False)
@click.pass_context
def snapshot_day(
    ctx: click.Context,
    host_id: str,
    date_str: str | None,
    output_path: Path | None,
    skip_opencode: bool,
) -> None:
    raw_config = _load_raw_config(ctx.obj.get("config_path"))
    host_meta = _load_host_meta(raw_config, host_id)
    if host_meta is None:
        raise click.ClickException(f"host config not found: {host_id}")

    try:
        target_date = date.fromisoformat(date_str) if date_str else date.today()
    except ValueError as exc:
        raise click.ClickException(f"invalid --date value: {date_str}") from exc

    config = ctx.obj["config"]
    opencode_sessions = None if skip_opencode else []
    snapshot = build_host_snapshot(
        client=object(),
        host_meta=host_meta,
        config=config,
        target_date=target_date,
        opencode_sessions=opencode_sessions,
    )
    _dump_snapshot(snapshot, output_path)


@main.command()
def version() -> None:
    click.echo(__version__)


@main.command("aggregate")
@click.option(
    "--in",
    "in_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
)
@click.option("--out", "out_path", type=click.Path(path_type=Path), required=True)
@click.option("--today", "today_str", default=None, help="YYYY-MM-DD override")
@click.pass_context
def aggregate_cmd(
    ctx: click.Context,
    in_dir: Path,
    out_path: Path,
    today_str: str | None,
) -> None:
    """Aggregate HostSnapshot JSON files from IN_DIR into a Dashboard JSON."""
    del ctx

    if aggregate is None:
        raise click.ClickException("aggregate_dashboard is unavailable")

    snapshots: list[HostSnapshot] = []
    for file_path in sorted(in_dir.glob("*.json")):
        try:
            snapshots.append(
                HostSnapshot.from_json(file_path.read_text(encoding="utf-8"))
            )
        except Exception as exc:
            click.echo(f"Warning: skipping {file_path.name}: {exc}", err=True)

    try:
        today = date.fromisoformat(today_str) if today_str else date.today()
    except ValueError as exc:
        raise click.ClickException(f"invalid --today value: {today_str}") from exc

    dashboard = aggregate(snapshots, today=today)
    out_path.write_text(
        json.dumps(dashboard.to_json(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    click.echo(f"Written to {out_path}")


@main.command("render")
@click.option(
    "--in",
    "in_path",
    type=click.Path(exists=True, path_type=Path),
    required=True,
)
@click.option("--out", "out_path", type=click.Path(path_type=Path), required=True)
@click.pass_context
def render_cmd(ctx: click.Context, in_path: Path, out_path: Path) -> None:
    """Render a Dashboard JSON into an SVG file."""
    del ctx

    if render_dashboard is None:
        raise click.ClickException("render_svg is unavailable")

    dashboard = Dashboard.from_json(in_path.read_text(encoding="utf-8"))
    svg = render_dashboard(dashboard)
    out_path.write_text(svg, encoding="utf-8")
    click.echo(f"Written to {out_path}")


@main.group()
@click.pass_context
def inspect(ctx):
    pass


@inspect.command("hosts")
@click.pass_context
def inspect_hosts(ctx):
    cfg: Config = ctx.obj["config"]
    client = AWClient(cfg.base_url, cfg.timeout_seconds)
    try:
        host_buckets = discover_host_buckets(client)
        for host, bmap in sorted(host_buckets.items()):
            click.echo(f"\n{host}:")
            for logical, bid in sorted(bmap.items()):
                click.echo(f"  {logical:8s} → {bid}")
    finally:
        client.close()


@inspect.command("buckets")
@click.pass_context
def inspect_buckets(ctx):
    cfg: Config = ctx.obj["config"]
    client = AWClient(cfg.base_url, cfg.timeout_seconds)
    try:
        buckets = client.list_buckets()
        for bid, info in sorted(buckets.items()):
            click.echo(f"{info.type:25s}  {info.hostname:30s}  {bid}")
    finally:
        client.close()


def _resolve_time(report_type, day_str, range_start, range_end, cfg):
    if report_type == "day":
        if not day_str:
            day_str = date.today().isoformat()
        d = date.fromisoformat(day_str)
        return day_range(d, cfg.timezone), "day"
    else:
        if not range_start or not range_end:
            click.echo("Error: range requires --start and --end", err=True)
            sys.exit(1)
        return parse_range(range_start, range_end, cfg.timezone), "range"


@main.command()
@click.argument("report_type", type=click.Choice(["day", "range"]))
@click.argument("day_str", required=False, default=None)
@click.option("--start", "range_start", default=None)
@click.option("--end", "range_end", default=None)
@click.option("--format", "fmt", type=click.Choice(["md", "json"]), default=None)
@click.option("--hosts", default=None)
@click.option(
    "-o", "--output", "output_path", type=click.Path(path_type=Path), default=None
)
@click.pass_context
def report(ctx, report_type, day_str, range_start, range_end, fmt, hosts, output_path):
    cfg: Config = ctx.obj["config"]
    if hosts:
        cfg.hosts = [h.strip() for h in hosts.split(",")]
    (start, end), rtype = _resolve_time(
        report_type, day_str, range_start, range_end, cfg
    )
    fmt = fmt or cfg.default_format
    client = AWClient(cfg.base_url, cfg.timeout_seconds)
    try:
        facts = build_report(client, start, end, rtype, cfg)
    finally:
        client.close()
    if fmt == "json":
        output = render_json(facts)
    else:
        output = render_markdown(facts)
    if output_path:
        output_path.write_text(output, encoding="utf-8")
        click.echo(f"Written to {output_path}")
    else:
        click.echo(output)


@main.command()
@click.argument("report_type", type=click.Choice(["day", "range"]))
@click.argument("day_str", required=False, default=None)
@click.option("--start", "range_start", default=None)
@click.option("--end", "range_end", default=None)
@click.option("--hosts", default=None)
@click.option(
    "-o", "--output", "output_path", type=click.Path(path_type=Path), default=None
)
@click.pass_context
def facts(ctx, report_type, day_str, range_start, range_end, hosts, output_path):
    cfg: Config = ctx.obj["config"]
    if hosts:
        cfg.hosts = [h.strip() for h in hosts.split(",")]
    (start, end), rtype = _resolve_time(
        report_type, day_str, range_start, range_end, cfg
    )
    client = AWClient(cfg.base_url, cfg.timeout_seconds)
    try:
        report_facts = build_report(client, start, end, rtype, cfg)
    finally:
        client.close()
    output = render_json(report_facts)
    if output_path:
        output_path.write_text(output, encoding="utf-8")
        click.echo(f"Written to {output_path}")
    else:
        click.echo(output)
