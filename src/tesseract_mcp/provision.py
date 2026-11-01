"""Provision a fresh Obsidian vault as a Tesseract mind database.

Downloads the curated community-plugin set (pinned in
vault-template/plugins.json) from each plugin's GitHub release, enables
them, applies opinionated settings where the vault has none, and installs
the Claude/ conventions tree. Operator CLI only — deliberately NOT an MCP
tool.

All network access goes through an injectable fetch(url) -> bytes | None
callable (the same injection pattern CliExtractor uses for subprocess.run),
so tests never touch the network.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .conventions import install as install_conventions

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE_DIR = REPO_ROOT / "vault-template"


class ProvisionError(Exception):
    """Raised when provisioning cannot proceed for a plugin or the vault."""


@dataclass
class PluginSpec:
    id: str
    repo: str
    version: str
    sha256: dict[str, str] = field(default_factory=dict)


def load_plugin_manifest(path: Path | None = None) -> list[PluginSpec]:
    p = path or TEMPLATE_DIR / "plugins.json"
    entries = json.loads(p.read_text(encoding="utf-8"))
    specs: list[PluginSpec] = []
    for entry in entries:
        for field in ("id", "repo", "version"):
            if not entry.get(field):
                raise ProvisionError(f"plugins.json entry missing '{field}': {entry}")
        hashes = entry.get("sha256") or {}
        if not isinstance(hashes, dict) or any(
            k not in ("manifest.json", "main.js", "styles.css") or
            not isinstance(v, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", v)
            for k, v in hashes.items()
        ):
            raise ProvisionError(f"invalid sha256 checksums for {entry['id']}")
        specs.append(PluginSpec(entry["id"], entry["repo"], entry["version"], hashes))
    return specs


RELEASE_URL = "https://github.com/{repo}/releases/download/{version}/{filename}"
USER_AGENT = "tesseract-mcp-provisioner"


def http_fetch(url: str) -> bytes | None:
    """GET a release asset. Returns None on 404 (asset simply not present);
    raises ProvisionError on any other network failure."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read()
    except HTTPError as e:
        if e.code == 404:
            return None
        raise ProvisionError(f"download failed {url}: HTTP {e.code}") from e
    except URLError as e:
        raise ProvisionError(f"download failed {url}: {e.reason}") from e


def _asset_url(spec: PluginSpec, filename: str) -> str:
    return RELEASE_URL.format(repo=spec.repo, version=spec.version, filename=filename)


def installed_version(vault_root: Path, plugin_id: str) -> str | None:
    mf = Path(vault_root) / ".obsidian" / "plugins" / plugin_id / "manifest.json"
    if not mf.is_file():
        return None
    try:
        return json.loads(mf.read_text(encoding="utf-8")).get("version")
    except (json.JSONDecodeError, OSError):
        return None


def install_plugin(vault_root: Path, spec: PluginSpec, fetch=http_fetch,
                   require_checksums: bool = False) -> str:
    vault_root = Path(vault_root)
    if installed_version(vault_root, spec.id) == spec.version:
        return "ok"
    manifest_bytes = fetch(_asset_url(spec, "manifest.json"))
    if manifest_bytes is None:
        raise ProvisionError(
            f"{spec.id}: no manifest.json in release {spec.version} of {spec.repo}"
        )
    manifest = json.loads(manifest_bytes)
    if manifest.get("id") != spec.id:
        raise ProvisionError(
            f"{spec.id}: release manifest declares id '{manifest.get('id')}' — refusing"
        )
    main_js = fetch(_asset_url(spec, "main.js"))
    if main_js is None:
        raise ProvisionError(f"{spec.id}: no main.js in release {spec.version}")
    styles = fetch(_asset_url(spec, "styles.css"))  # optional; None is fine
    for filename, data in (("manifest.json", manifest_bytes),
                           ("main.js", main_js), ("styles.css", styles)):
        if data is None:
            continue
        expected = spec.sha256.get(filename)
        if require_checksums and not expected:
            raise ProvisionError(f"{spec.id}: missing SHA-256 for {filename}")
        if expected and hashlib.sha256(data).hexdigest() != expected.lower():
            raise ProvisionError(f"{spec.id}: SHA-256 mismatch for {filename}")

    dest = vault_root / ".obsidian" / "plugins" / spec.id
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "manifest.json").write_bytes(manifest_bytes)
    (dest / "main.js").write_bytes(main_js)
    if styles is not None:
        (dest / "styles.css").write_bytes(styles)
    return "installed"


def enable_plugins(vault_root: Path, ids: list[str]) -> list[str]:
    """Merge ids into community-plugins.json. Never removes existing entries."""
    cfg = Path(vault_root) / ".obsidian" / "community-plugins.json"
    existing: list[str] = []
    if cfg.is_file():
        existing = json.loads(cfg.read_text(encoding="utf-8"))
    added = [i for i in ids if i not in existing]
    if added:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(existing + added, indent=2), encoding="utf-8")
    return added


def apply_overlays(vault_root: Path) -> list[str]:
    """Copy settings templates into the vault — only where nothing exists yet."""
    vault_root = Path(vault_root)
    applied: list[str] = []
    settings_dir = TEMPLATE_DIR / "settings"
    if not settings_dir.is_dir():
        return applied
    for src in sorted(settings_dir.glob("*/data.json")):
        plugin_id = src.parent.name
        dest = vault_root / ".obsidian" / "plugins" / plugin_id / "data.json"
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        applied.append(f"{plugin_id}/data.json")
    smart_env_src = settings_dir / "smart-env" / "smart_env.json"
    if smart_env_src.is_file():
        dest = vault_root / ".smart-env" / "smart_env.json"
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(smart_env_src.read_text(encoding="utf-8"), encoding="utf-8")
            applied.append(".smart-env/smart_env.json")
    return applied


NEXT_STEPS = """
Provisioning done. Remaining human steps:
 1. Open the vault in Obsidian once and turn OFF Restricted Mode
    (Settings -> Community plugins) so the installed plugins load.
 2. Complete LiveSync setup via its Setup-URI flow — server URI and the
    E2E passphrase live in your password manager, never in this repo.
 3. Register the vault with the MCP server (see README) and run the
    index_brain tool to build the semantic graph.
"""


def provision(vault_root: str | Path, fetch=http_fetch,
              selected_plugins: set[str] | None = None,
              require_checksums: bool = False,
              owner: str | None = None,
              scope: str = "vault") -> dict:
    vault_root = Path(vault_root)
    if not vault_root.is_dir():
        raise ProvisionError(f"Vault root does not exist: {vault_root}")
    if scope not in ("vault", "claude-only"):
        raise ProvisionError("invalid provisioning scope")
    all_specs = load_plugin_manifest()
    if selected_plugins is not None:
        unknown = set(selected_plugins) - {s.id for s in all_specs}
        if unknown:
            raise ProvisionError(f"unknown plugin IDs: {sorted(unknown)}")
    if scope == "claude-only" and selected_plugins:
        raise ProvisionError("cannot install plugins in claude-only scope")
    if scope == "vault":
        (vault_root / ".obsidian").mkdir(exist_ok=True)
    specs = ([] if scope == "claude-only" else [
        s for s in all_specs if selected_plugins is None or s.id in selected_plugins
    ])
    plugins: dict[str, str] = {}
    errors: dict[str, str] = {}
    for spec in specs:
        try:
            plugins[spec.id] = install_plugin(
                vault_root, spec, fetch, require_checksums=require_checksums
            )
        except ProvisionError as e:
            errors[spec.id] = str(e)

    enabled = (enable_plugins(
        vault_root, [s.id for s in specs if s.id not in errors]
    ) if scope == "vault" and specs else [])
    overlays = apply_overlays(vault_root) if scope == "vault" else []
    conventions = install_conventions(vault_root, owner=owner, scope=scope)
    return {
        "plugins": plugins,
        "errors": errors,
        "enabled": enabled,
        "overlays": overlays,
        "conventions": conventions,
    }


def check(vault_root: str | Path) -> dict:
    vault_root = Path(vault_root)
    report: dict[str, dict] = {}
    for spec in load_plugin_manifest():
        installed = installed_version(vault_root, spec.id)
        if installed == spec.version:
            status = "ok"
        elif installed is None:
            status = "missing"
        else:
            status = "drift"
        report[spec.id] = {
            "pinned": spec.version, "installed": installed, "status": status
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision an Obsidian vault as a Tesseract mind database."
    )
    parser.add_argument("vault", help="Path to the vault root")
    parser.add_argument(
        "--check", action="store_true",
        help="Report pinned vs installed plugin versions without changing anything",
    )
    selected = parser.add_mutually_exclusive_group()
    selected.add_argument("--all-plugins", action="store_true",
                          help="Explicitly opt into all curated plugins")
    selected.add_argument("--plugins", nargs="+", metavar="ID",
                          help="Install only selected plugin IDs")
    parser.add_argument("--require-checksums", action="store_true",
                        help="Fail closed if any downloaded asset lacks SHA-256")
    parser.add_argument("--owner", help="Name for newly created agent guides")
    parser.add_argument("--scope", choices=("vault", "claude-only"),
                        default="vault", help="Restrict provisioning to Claude/")
    args = parser.parse_args()
    if args.check:
        print(json.dumps(check(args.vault), indent=2))
        return
    plugins = None if args.all_plugins else set(args.plugins or [])
    report = provision(args.vault, selected_plugins=plugins,
                       require_checksums=args.require_checksums,
                       owner=args.owner, scope=args.scope)
    print(json.dumps(report, indent=2))
    if report["errors"]:
        print("\nWARNING: some plugins failed — re-run after checking pins/network.")
    if not args.all_plugins and not args.plugins:
        print("\nCommunity plugin installation skipped (opt in with --plugins or --all-plugins).")
    print(NEXT_STEPS)


if __name__ == "__main__":
    main()
