"""Part 2: owner templates, portable hook defaults, and read-only registration."""
import importlib.util
import io
import json
from pathlib import Path
import pytest
from tesseract_mcp import conventions, server

def test_custom_owner_and_non_overwrite(tmp_path):
    conventions.install(tmp_path, owner="Harvey")
    guide = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "Harvey" in guide and "{OWNER}" not in guide
    (tmp_path / "AGENTS.md").write_text("Custom")
    conventions.install(tmp_path, owner="Someone Else")
    assert (tmp_path / "AGENTS.md").read_text() == "Custom"

def test_owner_rejects_multiline(tmp_path):
    with pytest.raises(ValueError, match="single line"):
        conventions.install(tmp_path, owner="name\ninjected text")

def test_public_registration_filters_write_tools(monkeypatch):
    monkeypatch.setenv("TESSERACT_READONLY", "true")
    before = set(server.mcp._tool_manager._tools)
    def unregistered_test_tool():
        pass
    server.register_tool(unregistered_test_tool)
    assert set(server.mcp._tool_manager._tools) == before
    assert server._read_only_enabled()

def test_missing_vault_hook_does_not_block(tmp_path, monkeypatch, capsys):
    path = Path(__file__).resolve().parents[1] / "scripts" / "hooks" / "session-start.py"
    spec = importlib.util.spec_from_file_location("tesseract_part2_hook", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.delenv("TESSERACT_VAULT_PATH", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    mod.main()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "TESSERACT_VAULT_PATH" in captured.err
