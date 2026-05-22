import pytest

from asen_cli.tools.file import ListFilesTool, ReadFileChunkTool, ReadFileTool, WriteFileTool


@pytest.mark.asyncio
async def test_read_file_inside_workspace(tmp_path):
    target = tmp_path / "hello.txt"
    target.write_text("hello", encoding="utf-8")
    tool = ReadFileTool(tmp_path, max_file_bytes=100)

    result = await tool.execute({"path": "hello.txt"})

    assert result.ok
    assert result.content == "hello"


@pytest.mark.asyncio
async def test_read_file_blocks_outside_workspace(tmp_path):
    tool = ReadFileTool(tmp_path, max_file_bytes=100)

    result = await tool.execute({"path": "../outside.txt"})

    assert not result.ok
    assert "outside workspace" in result.error


@pytest.mark.asyncio
async def test_read_file_chunk_reads_line_range(tmp_path):
    target = tmp_path / "hello.txt"
    target.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    tool = ReadFileChunkTool(tmp_path, max_file_bytes=100)

    result = await tool.execute({"path": "hello.txt", "start_line": 2, "max_lines": 2})

    assert result.ok
    assert "hello.txt lines 2-3 of 4" in result.content
    assert "2: two" in result.content
    assert "3: three" in result.content
    assert "1: one" not in result.content


@pytest.mark.asyncio
async def test_write_file_requires_approval(tmp_path):
    tool = WriteFileTool(tmp_path, require_approval=True, confirm=lambda _: False)

    result = await tool.execute({"path": "new.txt", "content": "hello"})

    assert not result.ok
    assert not (tmp_path / "new.txt").exists()
    assert not (tmp_path / ".asen" / "checkpoints").exists()


@pytest.mark.asyncio
async def test_write_file_after_approval_creates_checkpoint(tmp_path):
    tool = WriteFileTool(tmp_path, require_approval=True, confirm=lambda _: True)

    result = await tool.execute({"path": "new.txt", "content": "hello"})

    assert result.ok
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello"
    checkpoints = list((tmp_path / ".asen" / "checkpoints").glob("*/meta.json"))
    assert len(checkpoints) == 1
    assert "Checkpoint saved as" in result.content
    assert result.meta["changed_files"][0]["path"] == "new.txt"
    assert result.meta["changed_files"][0]["change_type"] == "created"
    assert result.meta["checkpoints"][0]["checkpoint_id"]


@pytest.mark.asyncio
async def test_list_files(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "b.txt").write_text("b", encoding="utf-8")
    tool = ListFilesTool(tmp_path, max_output_chars=500)

    result = await tool.execute({"path": "."})

    assert result.ok
    assert "a.txt" in result.content
    assert "dir/b.txt" in result.content
