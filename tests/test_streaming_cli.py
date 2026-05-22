import json
from types import SimpleNamespace

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


def test_ask_passes_stream_and_json_flags(monkeypatch):
    captured = {}

    async def fake_ask(task, config_path, workspace, no_approval, verbose, stream, json_output):
        captured["task"] = task
        captured["stream"] = stream
        captured["json_output"] = json_output

    monkeypatch.setattr(app_module, "_ask", fake_ask)

    result = runner.invoke(app_module.app, ["ask", "hello", "--stream", "--json"])

    assert result.exit_code == 0
    assert captured == {"task": "hello", "stream": True, "json_output": True}


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


def test_checkpoint_list_json_outputs_items(tmp_path):
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
        ["checkpoint", "list", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["checkpoints"][0]["checkpoint_id"] == store.checkpoint_id


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


def test_checkpoint_diff_json_outputs_payload(tmp_path):
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
        ["checkpoint", "diff", store.checkpoint_id, "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["checkpoint"]["checkpoint_id"] == store.checkpoint_id
    assert payload["changed_files"][0]["path"] == "demo.py"
    assert "-print('old')" in payload["diff"]


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


def test_checkpoint_restore_json_requires_force(tmp_path):
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
        ["checkpoint", "restore", store.checkpoint_id, "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert "requires --force" in payload["error"]["message"]


def test_checkpoint_restore_json_outputs_actions(tmp_path):
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
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["actions"] == ["Restored demo.py"]


def test_ask_json_output_contains_changed_files(monkeypatch, tmp_path):
    checkpoint = CheckpointStore.create_file_checkpoint(
        tmp_path,
        tool_name="write_file",
        path=tmp_path / "demo.py",
        before="print('old')\n",
        after="print('new')\n",
    )
    assert checkpoint is not None

    class FakeAgent:
        def __init__(self, events):
            self.config = SimpleNamespace(workspace=tmp_path)
            self._events = events

        async def run(self, task):
            self._events.thinking(1)
            self._events.tool_call("write_file", {"path": "demo.py"})
            self._events.tool_result(
                "write_file",
                "done",
                payload={
                    "ok": True,
                    "content": "done",
                    "rendered": "done",
                    "error": None,
                    "error_type": None,
                    "retryable": False,
                    "meta": {
                        "changed_files": [
                            {
                                **checkpoint.changed_files_payload()[0],
                                "diff": checkpoint.render_diff(),
                            }
                        ],
                        "checkpoints": [checkpoint.metadata_payload()],
                    },
                },
            )
            return f"handled: {task}"

    def fake_build_agent(config_path, workspace, no_approval, console, stream):
        return FakeAgent(console.agent_events())

    monkeypatch.setattr(app_module, "_build_agent", fake_build_agent)

    result = runner.invoke(
        app_module.app,
        ["ask", "update demo", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["final_text"] == "handled: update demo"
    assert payload["changed_files"][0]["path"] == "demo.py"
    assert payload["checkpoints"][0]["checkpoint_id"] == checkpoint.checkpoint_id


def test_help_shows_stream_flags_json_and_checkpoint_commands():
    chat_help = runner.invoke(app_module.app, ["chat", "--help"])
    ask_help = runner.invoke(app_module.app, ["ask", "--help"])
    shell_help = runner.invoke(app_module.app, ["shell", "--help"])
    resume_help = runner.invoke(app_module.app, ["session", "resume", "--help"])
    checkpoint_help = runner.invoke(app_module.app, ["checkpoint", "--help"])
    checkpoint_list_help = runner.invoke(app_module.app, ["checkpoint", "list", "--help"])
    checkpoint_diff_help = runner.invoke(app_module.app, ["checkpoint", "diff", "--help"])

    assert chat_help.exit_code == 0
    assert ask_help.exit_code == 0
    assert shell_help.exit_code == 0
    assert resume_help.exit_code == 0
    assert checkpoint_help.exit_code == 0
    assert checkpoint_list_help.exit_code == 0
    assert checkpoint_diff_help.exit_code == 0
    assert "--stream" in chat_help.output
    assert "--no-stream" in chat_help.output
    assert "--stream" in ask_help.output
    assert "--no-stream" in ask_help.output
    assert "--json" in ask_help.output
    assert "--stream" in shell_help.output
    assert "--no-stream" in shell_help.output
    assert "--stream" in resume_help.output
    assert "--no-stream" in resume_help.output
    assert "list" in checkpoint_help.output
    assert "diff" in checkpoint_help.output
    assert "restore" in checkpoint_help.output
    assert "--json" in checkpoint_list_help.output
    assert "--json" in checkpoint_diff_help.output
