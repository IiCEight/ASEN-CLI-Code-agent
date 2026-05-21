import pytest

from asen_cli.utils.errors import SafetyError
from asen_cli.utils.safety import (
    assess_command_safety,
    is_dangerous_command,
    resolve_workspace_path,
    truncate_text,
)


def test_resolve_workspace_path_allows_inside(tmp_path):
    result = resolve_workspace_path(tmp_path, "src/main.py")
    assert result == (tmp_path / "src/main.py").resolve()


def test_resolve_workspace_path_blocks_outside(tmp_path):
    with pytest.raises(SafetyError):
        resolve_workspace_path(tmp_path, "../secret.txt")


def test_truncate_text_marks_omitted_chars():
    assert truncate_text("abcdef", 3) == "abc\n...[truncated 3 chars]"


def test_dangerous_command_detection():
    assert is_dangerous_command("sudo rm -rf /")
    assert is_dangerous_command("mkfs.ext4 /dev/sda")
    assert not is_dangerous_command("python hello.py")


def test_assess_command_safety_distinguishes_levels():
    assert assess_command_safety("git status").level == "safe"
    assert assess_command_safety("git reset --hard HEAD").level == "confirm"
    assert assess_command_safety("sudo rm -rf /").level == "blocked"
