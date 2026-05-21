from typer.testing import CliRunner

import asen_cli.app as app_module

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



def test_help_shows_stream_flags():
    chat_help = runner.invoke(app_module.app, ["chat", "--help"])
    ask_help = runner.invoke(app_module.app, ["ask", "--help"])

    assert chat_help.exit_code == 0
    assert ask_help.exit_code == 0
    assert "--stream" in chat_help.output
    assert "--no-stream" in chat_help.output
    assert "--stream" in ask_help.output
    assert "--no-stream" in ask_help.output
