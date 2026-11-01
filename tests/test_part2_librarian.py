"""Part 2 safe-default regression tests."""
import sys
import pytest
from tesseract_mcp import librarian, organizer
from tesseract_mcp.vault import Vault

def test_librarian_cli_defaults_to_preview(monkeypatch, tmp_path, capsys):
    captured = []
    monkeypatch.setattr(librarian, "run_sweep", lambda vault, **kw: (captured.append(kw) or {"errors": {}}))
    monkeypatch.setattr(librarian, "format_report", lambda *a: "preview")
    monkeypatch.setattr(sys, "argv", ["librarian", str(tmp_path)])
    librarian.main()
    assert captured[0]["apply"] is False
    assert "preview" in capsys.readouterr().out

def test_librarian_cli_explicit_apply_and_scope(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(librarian, "run_sweep", lambda vault, **kw: (captured.append(kw) or {"errors": {}}))
    monkeypatch.setattr(sys, "argv", ["librarian", str(tmp_path), "--apply", "--scope", "claude-only"])
    librarian.main()
    assert captured[0] == {"apply": True, "scope": "claude-only"}

def test_cli_rejects_both_modes(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["librarian", str(tmp_path), "--apply", "--dry-run"])
    with pytest.raises(SystemExit):
        librarian.main()

def test_organizer_rejects_invalid_scope_and_cap(tmp_path):
    with pytest.raises(ValueError, match="scope"):
        organizer.run_sweep(Vault(tmp_path), scope="other")
    with pytest.raises(ValueError, match="max_moves"):
        organizer.run_sweep(Vault(tmp_path), max_moves=-1)
