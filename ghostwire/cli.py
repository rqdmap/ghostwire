from __future__ import annotations

import secrets
import sys
import tomllib
from datetime import date
from pathlib import Path

import click

from . import __version__
from .aw_client import AWClient
from .config import DEFAULT_CONFIG_PATHS, load_config
from .models import HostMeta
from .snapshot import build_host_snapshot
from .uploader import UploadError, parse_date, resolve_token, upload_snapshot


def _resolve_config_path(config_path: Path | None) -> Path | None:
    if config_path and config_path.exists():
        return config_path
    for candidate in DEFAULT_CONFIG_PATHS:
        if candidate.exists():
            return candidate
    return None


def _load_raw_config(config_path: Path | None) -> dict:
    resolved = _resolve_config_path(config_path)
    if resolved is None:
        return {}
    with resolved.open("rb") as fh:
        return tomllib.load(fh)


def _load_host_meta(raw: dict, host_id: str) -> HostMeta:
    section = raw.get("host_meta", {}).get(host_id)
    if not isinstance(section, dict):
        raise click.ClickException(f"host config not found: [host_meta.{host_id}]")
    label = section.get("label")
    platform = section.get("platform")
    if not isinstance(label, str) or not label.strip():
        raise click.ClickException(f"missing host_meta.{host_id}.label")
    if not isinstance(platform, str) or not platform.strip():
        raise click.ClickException(f"missing host_meta.{host_id}.platform")
    return HostMeta(id=str(section.get("id", host_id)), label=label, platform=platform)


def _load_upload_section(raw: dict) -> dict:
    section = raw.get("upload", {})
    return section if isinstance(section, dict) else {}


@click.group()
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
@click.pass_context
def main(ctx: click.Context, config_path: Path | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["config"] = load_config(config_path)


@main.command()
def version() -> None:
    click.echo(__version__)


@main.command()
@click.option("--host", "host_id", required=True)
@click.option("--date", "date_str", default=None, help="YYYY-MM-DD, default today")
@click.option("--out", "out_path", type=click.Path(path_type=Path), default=None)
@click.option("--skip-opencode", is_flag=True, default=False)
@click.pass_context
def collect(
    ctx: click.Context,
    host_id: str,
    date_str: str | None,
    out_path: Path | None,
    skip_opencode: bool,
) -> None:
    """Build a HostSnapshot from local AW + OpenCode and write JSON."""
    raw = _load_raw_config(ctx.obj.get("config_path"))
    host_meta = _load_host_meta(raw, host_id)
    target_date = parse_date(date_str)

    cfg = ctx.obj["config"]
    client = AWClient(cfg.base_url, cfg.timeout_seconds)
    try:
        snapshot = build_host_snapshot(
            client=client,
            host_meta=host_meta,
            config=cfg,
            target_date=target_date,
            opencode_sessions=[] if skip_opencode else None,
        )
    finally:
        client.close()

    payload = snapshot.to_json()
    if out_path:
        out_path.write_text(payload + "\n", encoding="utf-8")
    else:
        click.echo(payload)


@main.command("upload")
@click.option(
    "--in",
    "in_path",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="HostSnapshot JSON to upload",
)
@click.option("--server", "server_url", default=None)
@click.option("--token", default=None)
@click.option("--token-env", default="GHOSTWIRE_UPLOAD_TOKEN")
@click.pass_context
def upload(
    ctx: click.Context,
    in_path: Path,
    server_url: str | None,
    token: str | None,
    token_env: str | None,
) -> None:
    """Upload an existing HostSnapshot to the telemetry server."""
    from .models import HostSnapshot

    raw = _load_raw_config(ctx.obj.get("config_path"))
    upload_cfg = _load_upload_section(raw)
    server = server_url or upload_cfg.get("server_url")
    if not server:
        raise click.ClickException("--server or [upload].server_url required")

    try:
        resolved_token = resolve_token(token, token_env)
    except UploadError as exc:
        raise click.ClickException(str(exc)) from exc

    snapshot = HostSnapshot.from_json(in_path.read_text(encoding="utf-8"))
    try:
        endpoint = upload_snapshot(snapshot, server, resolved_token)
    except UploadError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Uploaded → {endpoint}")


@main.command("collect-and-upload")
@click.option("--host", "host_id", required=True)
@click.option("--date", "date_str", default=None)
@click.option("--server", "server_url", default=None)
@click.option("--token", default=None)
@click.option("--token-env", default="GHOSTWIRE_UPLOAD_TOKEN")
@click.option("--skip-opencode", is_flag=True, default=False)
@click.option(
    "--save",
    "save_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Also write the snapshot JSON to this local file",
)
@click.pass_context
def collect_and_upload(
    ctx: click.Context,
    host_id: str,
    date_str: str | None,
    server_url: str | None,
    token: str | None,
    token_env: str | None,
    skip_opencode: bool,
    save_path: Path | None,
) -> None:
    """One-shot: build snapshot from local sources and PUT to the server."""
    raw = _load_raw_config(ctx.obj.get("config_path"))
    upload_cfg = _load_upload_section(raw)
    server = server_url or upload_cfg.get("server_url")
    if not server:
        raise click.ClickException("--server or [upload].server_url required")

    try:
        resolved_token = resolve_token(token, token_env)
    except UploadError as exc:
        raise click.ClickException(str(exc)) from exc

    host_meta = _load_host_meta(raw, host_id)
    target_date = parse_date(date_str)
    cfg = ctx.obj["config"]
    client = AWClient(cfg.base_url, cfg.timeout_seconds)
    try:
        snapshot = build_host_snapshot(
            client=client,
            host_meta=host_meta,
            config=cfg,
            target_date=target_date,
            opencode_sessions=[] if skip_opencode else None,
        )
    finally:
        client.close()

    if save_path:
        save_path.write_text(snapshot.to_json() + "\n", encoding="utf-8")

    try:
        endpoint = upload_snapshot(snapshot, server, resolved_token)
    except UploadError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Uploaded {host_id} {target_date} → {endpoint}")


@main.command("serve")
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    default=Path("/var/lib/ghostwire"),
)
@click.option("--host", "bind_host", default="0.0.0.0")
@click.option("--port", default=8000, type=int)
@click.option("--host-token-env", default="GHOSTWIRE_HOST_TOKEN")
@click.option("--read-token-env", default="GHOSTWIRE_READ_TOKEN")
def serve(
    data_dir: Path,
    bind_host: str,
    port: int,
    host_token_env: str,
    read_token_env: str,
) -> None:
    """Run the telemetry server."""
    import os

    host_token = os.environ.get(host_token_env)
    read_token = os.environ.get(read_token_env)
    if not host_token or not read_token:
        raise click.ClickException(
            f"set {host_token_env} and {read_token_env} env vars"
        )
    from .server import run

    run(
        data_dir=data_dir,
        host_token=host_token,
        read_token=read_token,
        host=bind_host,
        port=port,
    )


@main.command("gen-token")
@click.option("--bytes", "n_bytes", default=32, type=int)
def gen_token(n_bytes: int) -> None:
    """Generate a URL-safe random token suitable for GHOSTWIRE_*_TOKEN."""
    click.echo(secrets.token_urlsafe(n_bytes))


if __name__ == "__main__":
    sys.exit(main())
