from __future__ import annotations

import tomllib
from datetime import date
from importlib import import_module
from pathlib import Path

import click

from . import __version__
from .config import DEFAULT_CONFIG_PATHS, load_config
from .models import HostMeta, HostSnapshot

build_host_snapshot = import_module("aw_report.snapshot").build_host_snapshot


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
