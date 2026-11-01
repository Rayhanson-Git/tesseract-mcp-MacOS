"""Part 2: extractor must not expose tools to untrusted notes."""
from tesseract_mcp.extractor import CliExtractor

class Result:
    returncode = 0
    stdout = '{"entities": [], "relations": []}'
    stderr = ""

def test_codex_readonly_and_ephemeral():
    calls = []
    def runner(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Result()
    CliExtractor(backend="codex", runner=runner, which=lambda exe: exe).extract("n.md", "untrusted")
    cmd, kwargs = calls[0]
    assert cmd[:2] == ["codex", "exec"]
    assert cmd[cmd.index("--sandbox")+1] == "read-only"
    assert "--ephemeral" in cmd and "--skip-git-repo-check" in cmd
    assert "tesseract-extractor-" in kwargs["cwd"]

def test_claude_disables_builtin_and_mcp_tools():
    calls = []
    def runner(cmd, **kwargs):
        calls.append(cmd)
        return Result()
    CliExtractor(backend="claude", runner=runner, which=lambda exe: exe).extract("n.md", "untrusted")
    cmd = calls[0]
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--tools")+1] == ""
    assert cmd[cmd.index("--disallowedTools")+1] == "mcp__*"
    assert cmd[cmd.index("--max-turns")+1] == "1"
