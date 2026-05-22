import json
import sys

from typer.testing import CliRunner

from asen_cli.app import app

runner = CliRunner()


def test_mcp_add_and_list_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    add_result = runner.invoke(
        app,
        [
            "mcp",
            "add",
            "filesystem-demo",
            sys.executable,
            "--arg",
            "-m",
            "--arg",
            "asen_cli.mcp.demo_server",
            "--cwd",
            str(tmp_path),
            "--description",
            "Filesystem demo server",
        ],
    )

    assert add_result.exit_code == 0

    list_result = runner.invoke(app, ["mcp", "list", "--json", "--workspace", str(tmp_path)])

    assert list_result.exit_code == 0
    payload = json.loads(list_result.output)
    assert payload["ok"] is True
    assert payload["servers"][0]["name"] == "filesystem-demo"
    assert payload["servers"][0]["command"] == sys.executable


def test_mcp_tools_and_call_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "hello.txt"
    target.write_text("hello from cli\n", encoding="utf-8")
    config_dir = tmp_path / ".asen"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "\n".join(
            [
                "mcp_servers:",
                "  filesystem-demo:",
                f"    command: {json.dumps(sys.executable)}",
                "    args:",
                '      - "-m"',
                '      - "asen_cli.mcp.demo_server"',
                f"    cwd: {json.dumps(str(tmp_path))}",
                "    timeout_seconds: 5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    tools_result = runner.invoke(
        app,
        ["mcp", "tools", "filesystem-demo", "--workspace", str(tmp_path), "--json"],
    )
    assert tools_result.exit_code == 0
    tools_payload = json.loads(tools_result.output)
    tool_names = {item["name"] for item in tools_payload["tools"]}
    assert "read_file" in tool_names

    call_result = runner.invoke(
        app,
        [
            "mcp",
            "call",
            "filesystem-demo",
            "read_file",
            '{"path": "hello.txt"}',
            "--workspace",
            str(tmp_path),
            "--json",
        ],
    )
    assert call_result.exit_code == 0
    call_payload = json.loads(call_result.output)
    assert call_payload["ok"] is True
    assert "hello from cli" in call_payload["rendered"]


def test_mcp_call_json_rejects_non_object_arguments(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / ".asen"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "\n".join(
            [
                "mcp_servers:",
                "  demo:",
                f"    command: {json.dumps(sys.executable)}",
                "    args:",
                '      - "-m"',
                '      - "asen_cli.mcp.demo_server"',
                f"    cwd: {json.dumps(str(tmp_path))}",
                "    timeout_seconds: 5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["mcp", "call", "demo", "read_file", "[]", "--workspace", str(tmp_path), "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert "JSON object" in payload["error"]["message"]
