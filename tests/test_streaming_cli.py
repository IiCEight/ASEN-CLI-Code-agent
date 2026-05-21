from typer.testing import CliRunner

import asen_cli.app as app_module
from asen_cli.core.checkpoint_store import CheckpointStore

runner = CliRunner()


def test_chat_passes_no_stream_flag(monkeypatch):
    captured = {}

    async def fake_chat(config_path, workspace, no_approval, verbose, stream):
        captured["stream"] = stream

    monkeypatch.setattr(app_module, "_chat", fake_chat)

    result = runner.invoke(app_module.app, ["chat", "--no-stream"])

    assert result.exit_code == 0
    assert captured["stream"] is False


def test_ask_passes_stream_flag(monkeypatch):
    captured = {}

    async def fake_ask(task, config_path, workspace, no_approval, verbose, stream):
        captured["task"] = task
        captured["stream"] = stream

    monkeypatch.setattr(app_module, "_ask", fake_ask)

    result = runner.invoke(app_module.app, ["ask", "hello", "--stream"])

    assert result.exit_code == 0
    assert captured == {"task": "hello", "stream": True}


def test_shell_passes_no_stream_flag(monkeypatch):
    captured = {}

    async def fake_shell(config_path, workspace, no_approval, verbose, stream):
        captured["stream"] = stream

    monkeypatch.setattr(app_module, "_shell", fake_shell)

    result = runner.invoke(app_module.app, ["shell", "--no-stream"])

    assert result.exit_code == 0
    assert captured["stream"] is False


def test_session_resume_passes_no_stream_flag(monkeypatch):
    captured = {}

    async def fake_resume(session_id, config_path, workspace, no_approval, verbose, stream):
        captured["session_id"] = session_id
        captured["stream"] = stream

    monkeypatch.setattr(app_module, "_resume_session", fake_resume)

    result = runner.invoke(app_module.app, ["session", "resume", "demo-session", "--no-stream"])

    assert result.exit_code == 0
    assert captured == {"session_id": "demo-session", "stream": False}


def test_session_list_empty_state(tmp_path):
    result = runner.invoke(app_module.app, ["session", "list", "--workspace", str(tmp_path)])

    assert result.exit_code == 0
    assert "No saved sessions yet" in result.output


def test_checkpoint_list_empty_state(tmp_path):
    result = runner.invoke(
        app_module.app,
        ["checkpoint", "list", "--workspace", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "No checkpoints yet" in result.output


def test_checkpoint_diff_outputs_saved_patch(tmp_path):
    store = CheckpointStore.create_file_checkpoint(
        tmp_path,
        tool_name="write_file",
        path=tmp_path / "demo.py",
        before="print('old')\n",
        after="print('new')\n",
    )

    assert store is not None
    result = runner.invoke(
        app_module.app,
        ["checkpoint", "diff", store.checkpoint_id, "--workspace", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "-print('old')" in result.output
    assert "+print('new')" in result.output


def test_checkpoint_restore_force_reverts_file(tmp_path):
    target = tmp_path / "demo.py"
    target.write_text("print('new')\n", encoding="utf-8")
    store = CheckpointStore.create_file_checkpoint(
        tmp_path,
        tool_name="replace_in_file",
        path=target,
        before="print('old')\n",
        after="print('new')\n",
    )

    assert store is not None
    result = runner.invoke(
        app_module.app,
        [
            "checkpoint",
            "restore",
            store.checkpoint_id,
            "--workspace",
            str(tmp_path),
            "--force",
        ],
    )

    assert result.exit_code == 0
    assert target.read_text(encoding="utf-8") == "print('old')\n"
    assert "Restored checkpoint" in result.output


def test_help_shows_stream_flags_and_checkpoint_commands():
    chat_help = runner.invoke(app_module.app, ["chat", "--help"])
    ask_help = runner.invoke(app_module.app, ["ask", "--help"])
    shell_help = runner.invoke(app_module.app, ["shell", "--help"])
    resume_help = runner.invoke(app_module.app, ["session", "resume", "--help"])
    checkpoint_help = runner.invoke(app_module.app, ["checkpoint", "--help"])

    assert chat_help.exit_code == 0
    assert ask_help.exit_code == 0
    assert shell_help.exit_code == 0
    assert resume_help.exit_code == 0
    assert checkpoint_help.exit_code == 0
    assert "--stream" in chat_help.output
    assert "--no-stream" in chat_help.output
    assert "--stream" in ask_help.output
    assert "--no-stream" in ask_help.output
    assert "--stream" in shell_help.output
    assert "--no-stream" in shell_help.output
    assert "--stream" in resume_help.output
    assert "--no-stream" in resume_help.output
    assert "list" in checkpoint_help.output
    assert "diff" in checkpoint_help.output
    assert "restore" in checkpoint_help.output
