"""Part 2: opt-in provisioning, scope and downloaded asset integrity."""
import hashlib
import json
import sys
import pytest

from tesseract_mcp import provision as provision_mod
from tesseract_mcp.provision import PluginSpec, ProvisionError, install_plugin, provision

def assets_for(spec):
    base = f"https://github.com/{spec.repo}/releases/download/{spec.version}"
    return {f"{base}/manifest.json": json.dumps({"id": spec.id, "version": spec.version}).encode(),
            f"{base}/main.js": b"console.log('safe')",
            f"{base}/styles.css": b".safe {}"}

def test_hash_verification_success_and_mismatch(tmp_path):
    base = PluginSpec("x", "owner/plugin", "1")
    assets = assets_for(base)
    digests = {k.rsplit("/", 1)[-1]: hashlib.sha256(v).hexdigest() for k, v in assets.items()}
    spec = PluginSpec(base.id, base.repo, base.version, digests)
    assert install_plugin(tmp_path, spec, assets.get, require_checksums=True) == "installed"
    spec = PluginSpec(base.id, base.repo, base.version, dict(digests, **{"main.js": "0"*64}))
    with pytest.raises(ProvisionError, match="SHA-256 mismatch"):
        install_plugin(tmp_path / "other", spec, assets.get, require_checksums=True)

def test_missing_hash_fails_closed(tmp_path):
    spec = PluginSpec("x", "owner/plugin", "1")
    with pytest.raises(ProvisionError, match="missing SHA-256"):
        install_plugin(tmp_path, spec, assets_for(spec).get, require_checksums=True)
    assert not (tmp_path / ".obsidian").exists()

def test_claude_only_scope_has_no_root_guide_or_plugins(tmp_path):
    report = provision(tmp_path, selected_plugins=set(), scope="claude-only")
    assert report["plugins"] == {}
    assert (tmp_path / "Claude" / "README.md").exists()
    assert not (tmp_path / ".obsidian").exists()
    assert not (tmp_path / "AGENTS.md").exists()

def test_claude_only_rejects_plugin_install(tmp_path):
    with pytest.raises(ProvisionError, match="cannot install plugins"):
        provision(tmp_path, selected_plugins={"dataview"}, scope="claude-only")

def test_unknown_plugins_rejected_without_modification(tmp_path):
    with pytest.raises(ProvisionError, match="unknown plugin IDs"):
        provision(tmp_path, selected_plugins={"not-real"})
    assert not (tmp_path / ".obsidian").exists()
