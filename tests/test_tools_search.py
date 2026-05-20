import pytest

from asen_cli.tools.search import (
    FindFilesTool,
    GrepContextTool,
    ReadManyFilesTool,
    SearchTextTool,
    ShowTreeTool,
)


@pytest.mark.asyncio
async def test_find_files_matches_filename_pattern(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "README.md").write_text("docs", encoding="utf-8")
    tool = FindFilesTool(tmp_path, max_output_chars=1000)

    result = await tool.execute({"pattern": "*.py"})

    assert result.ok
    assert "src/app.py" in result.content
    assert "README.md" not in result.content


@pytest.mark.asyncio
async def test_search_text_finds_literal_text(tmp_path):
    (tmp_path / "agent.py").write_text("class Agent:\n    pass\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("agent lowercase\n", encoding="utf-8")
    tool = SearchTextTool(tmp_path, max_output_chars=1000)

    result = await tool.execute({"query": "Agent", "file_pattern": "*.py"})

    assert result.ok
    assert "agent.py:1" in result.content
    assert "notes.txt" not in result.content


@pytest.mark.asyncio
async def test_grep_context_returns_surrounding_lines(tmp_path):
    (tmp_path / "sample.py").write_text("one\ntwo\nneedle\nfour\n", encoding="utf-8")
    tool = GrepContextTool(tmp_path, max_output_chars=1000)

    result = await tool.execute(
        {"pattern": "need.*", "file_pattern": "*.py", "context_lines": 1}
    )

    assert result.ok
    assert "-- sample.py:3 --" in result.content
    assert "  2: two" in result.content
    assert "> 3: needle" in result.content
    assert "  4: four" in result.content


@pytest.mark.asyncio
async def test_show_tree_displays_compact_tree(tmp_path):
    (tmp_path / "src" / "asen").mkdir(parents=True)
    (tmp_path / "src" / "asen" / "app.py").write_text("", encoding="utf-8")
    tool = ShowTreeTool(tmp_path, max_output_chars=1000)

    result = await tool.execute({"max_depth": 3})

    assert result.ok
    assert "./" in result.content
    assert "src/" in result.content
    assert "asen/" in result.content


@pytest.mark.asyncio
async def test_read_many_files_reads_multiple_files(tmp_path):
    (tmp_path / "a.py").write_text("aaa", encoding="utf-8")
    (tmp_path / "b.py").write_text("bbb", encoding="utf-8")
    tool = ReadManyFilesTool(tmp_path, max_file_bytes=100, max_output_chars=1000)

    result = await tool.execute({"paths": ["a.py", "b.py"]})

    assert result.ok
    assert "## a.py" in result.content
    assert "aaa" in result.content
    assert "## b.py" in result.content
    assert "bbb" in result.content


@pytest.mark.asyncio
async def test_search_tools_block_outside_workspace(tmp_path):
    tool = SearchTextTool(tmp_path, max_output_chars=1000)

    result = await tool.execute({"query": "secret", "path": ".."})

    assert not result.ok
    assert result.error_type == "safety_error"
