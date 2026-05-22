import difflib

import pytest

from asen_cli.tools.edit import ApplyPatchTool, ReplaceInFileTool


@pytest.mark.asyncio
async def test_replace_in_file_dry_run_does_not_write(tmp_path):
    target = tmp_path / "hello.py"
    target.write_text("def greeting():\n    return 'hello'\n", encoding="utf-8")
    tool = ReplaceInFileTool(
        tmp_path,
        require_approval=False,
        max_output_chars=2000,
    )

    result = await tool.execute(
        {
            "path": "hello.py",
            "old_text": "return 'hello'",
            "new_text": "return 'hello world'",
            "dry_run": True,
        }
    )

    assert result.ok
    assert "Dry run only" in result.content
    assert "-    return 'hello'" in result.content
    assert "+    return 'hello world'" in result.content
    assert target.read_text(encoding="utf-8") == "def greeting():\n    return 'hello'\n"


@pytest.mark.asyncio
async def test_replace_in_file_requires_unique_match(tmp_path):
    target = tmp_path / "sample.txt"
    target.write_text("hello\nhello\n", encoding="utf-8")
    tool = ReplaceInFileTool(
        tmp_path,
        require_approval=False,
        max_output_chars=2000,
    )

    result = await tool.execute(
        {"path": "sample.txt", "old_text": "hello", "new_text": "hi"}
    )

    assert not result.ok
    assert result.error_type == "replacement_count_mismatch"
    assert target.read_text(encoding="utf-8") == "hello\nhello\n"


@pytest.mark.asyncio
async def test_replace_in_file_after_approval_writes_and_checkpoints(tmp_path):
    target = tmp_path / "hello.py"
    target.write_text("print('old')\n", encoding="utf-8")
    tool = ReplaceInFileTool(
        tmp_path,
        require_approval=True,
        confirm=lambda message: "-print('old')" in message,
        max_output_chars=2000,
    )

    result = await tool.execute(
        {"path": "hello.py", "old_text": "old", "new_text": "new"}
    )

    assert result.ok
    assert target.read_text(encoding="utf-8") == "print('new')\n"
    snapshots = list((tmp_path / ".asen" / "snapshots").rglob("hello.py"))
    checkpoints = list((tmp_path / ".asen" / "checkpoints").glob("*/meta.json"))
    assert len(snapshots) == 1
    assert snapshots[0].read_text(encoding="utf-8") == "print('old')\n"
    assert len(checkpoints) == 1
    assert "Checkpoint saved as" in result.content


@pytest.mark.asyncio
async def test_replace_in_file_rejected_by_user(tmp_path):
    target = tmp_path / "hello.py"
    target.write_text("print('old')\n", encoding="utf-8")
    tool = ReplaceInFileTool(
        tmp_path,
        require_approval=True,
        confirm=lambda _: False,
        max_output_chars=2000,
    )

    result = await tool.execute(
        {"path": "hello.py", "old_text": "old", "new_text": "new"}
    )

    assert not result.ok
    assert result.error_type == "user_rejected"
    assert target.read_text(encoding="utf-8") == "print('old')\n"


@pytest.mark.asyncio
async def test_apply_patch_dry_run(tmp_path):
    target = tmp_path / "hello.py"
    original = "def greeting():\n    return 'hello'\n"
    updated = "def greeting(name='world'):\n    return f'hello {name}'\n"
    target.write_text(original, encoding="utf-8")
    patch = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile="a/hello.py",
            tofile="b/hello.py",
        )
    )
    tool = ApplyPatchTool(
        tmp_path,
        require_approval=False,
        max_output_chars=2000,
    )

    result = await tool.execute({"path": "hello.py", "patch": patch, "dry_run": True})

    assert result.ok
    assert "Dry run only" in result.content
    assert "+def greeting(name='world'):" in result.content
    assert target.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_apply_patch_writes_after_approval_and_creates_checkpoint(tmp_path):
    target = tmp_path / "hello.py"
    original = "one\ntwo\nthree\n"
    updated = "one\nTWO\nthree\n"
    target.write_text(original, encoding="utf-8")
    patch = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile="a/hello.py",
            tofile="b/hello.py",
        )
    )
    tool = ApplyPatchTool(
        tmp_path,
        require_approval=True,
        confirm=lambda message: "-two" in message and "+TWO" in message,
        max_output_chars=2000,
    )

    result = await tool.execute({"path": "hello.py", "patch": patch})

    assert result.ok
    assert target.read_text(encoding="utf-8") == updated
    assert list((tmp_path / ".asen" / "snapshots").rglob("hello.py"))
    assert list((tmp_path / ".asen" / "checkpoints").glob("*/meta.json"))
    assert "Checkpoint saved as" in result.content
    assert result.meta["changed_files"][0]["path"] == "hello.py"
    assert result.meta["checkpoints"][0]["checkpoint_id"]


@pytest.mark.asyncio
async def test_apply_patch_reports_conflict(tmp_path):
    target = tmp_path / "hello.py"
    target.write_text("actual\n", encoding="utf-8")
    patch = "--- a/hello.py\n+++ b/hello.py\n@@ -1 +1 @@\n-expected\n+updated\n"
    tool = ApplyPatchTool(
        tmp_path,
        require_approval=False,
        max_output_chars=2000,
    )

    result = await tool.execute({"path": "hello.py", "patch": patch})

    assert not result.ok
    assert result.error_type == "patch_conflict"
    assert result.retryable is True
    assert target.read_text(encoding="utf-8") == "actual\n"
