import pytest

from asen_cli.config import AsenConfig
from asen_cli.core.session import ChatSession
from asen_cli.tools.base import ToolResult


class FakeTools:
    def schemas(self):
        return [{"name": "read_file", "description": "Read a file."}]


class FakeContext:
    def __init__(self):
        self.tool_messages = []

    def add_tool(self, name, content):
        self.tool_messages.append((name, content))


class FakeAgent:
    def __init__(self):
        self.tools = FakeTools()
        self.calls = []
        self.context = FakeContext()

    async def run(self, user_input):
        self.calls.append(user_input)
        return f"answer: {user_input}"


class FakeInputReader:
    def __init__(self, inputs, multiline=""):
        self.inputs = list(inputs)
        self.multiline = multiline

    async def read(self):
        return self.inputs.pop(0)

    async def read_multiline(self, *, end_marker="EOF"):
        return self.multiline


class FakeShellRunner:
    def __init__(self, result=None):
        self.commands = []
        self.result = result or ToolResult.success("exit_code=0\ncommand ok")

    async def execute(self, raw_command):
        self.commands.append(raw_command)
        return self.result


class RecordingConsole:
    def __init__(self):
        self.events = []

    def title(self, mode="chat"):
        self.events.append(("title", mode))

    def clear(self, mode="chat"):
        self.events.append(("clear", mode))

    def info(self, message):
        self.events.append(("info", message))

    def error(self, message):
        self.events.append(("error", message))

    def assistant(self, message):
        self.events.append(("assistant", message))

    def tools(self, schemas):
        self.events.append(("tools", schemas))

    def config(self, data):
        self.events.append(("config", data))

    def help(self, message):
        self.events.append(("help", message))

    def paste_hint(self):
        self.events.append(("paste_hint", None))

    def goodbye(self):
        self.events.append(("goodbye", None))

    def shell_command(self, command):
        self.events.append(("shell_command", command))

    def shell_result(self, command, rendered):
        self.events.append(("shell_result", command, rendered))


@pytest.mark.asyncio
async def test_session_handles_slash_commands(tmp_path):
    agent = FakeAgent()
    console = RecordingConsole()
    session = ChatSession(
        agent=agent,
        config=AsenConfig(workspace=tmp_path, api_key="secret"),
        console=console,
        input_reader=FakeInputReader(["/help", "/tools", "/config", "/clear", "/exit"]),
        shell_runner=FakeShellRunner(),
    )

    await session.run()

    kinds = [kind for kind, *_ in console.events]
    assert "tools" in kinds
    assert "config" in kinds
    assert "clear" in kinds
    assert agent.calls == []
    config_event = next(data for kind, data in console.events if kind == "config")
    assert config_event["api_key"] == "***"


@pytest.mark.asyncio
async def test_session_routes_regular_input_to_agent(tmp_path):
    agent = FakeAgent()
    console = RecordingConsole()
    session = ChatSession(
        agent=agent,
        config=AsenConfig(workspace=tmp_path),
        console=console,
        input_reader=FakeInputReader(["read hello.py", "/exit"]),
        shell_runner=FakeShellRunner(),
    )

    await session.run()

    assert agent.calls == ["read hello.py"]
    assert ("assistant", "answer: read hello.py") in console.events


@pytest.mark.asyncio
async def test_session_paste_routes_multiline_to_agent(tmp_path):
    agent = FakeAgent()
    console = RecordingConsole()
    session = ChatSession(
        agent=agent,
        config=AsenConfig(workspace=tmp_path),
        console=console,
        input_reader=FakeInputReader(["/paste", "/exit"], multiline="line1\nline2"),
        shell_runner=FakeShellRunner(),
    )

    await session.run()

    assert agent.calls == ["line1\nline2"]


@pytest.mark.asyncio
async def test_session_routes_bang_command_to_shell_and_context(tmp_path):
    agent = FakeAgent()
    console = RecordingConsole()
    shell_runner = FakeShellRunner(ToolResult.success("exit_code=1\npytest failed"))
    session = ChatSession(
        agent=agent,
        config=AsenConfig(workspace=tmp_path),
        console=console,
        input_reader=FakeInputReader(["!pytest -q", "summarize that", "/exit"]),
        shell_runner=shell_runner,
    )

    await session.run()

    assert shell_runner.commands == ["pytest -q"]
    assert agent.calls == ["summarize that"]
    assert ("shell_command", "pytest -q") in console.events
    assert any(event[0] == "shell_result" for event in console.events)
    assert agent.context.tool_messages == [
        ("shell", "command=pytest -q\nexit_code=1\npytest failed")
    ]


@pytest.mark.asyncio
async def test_shell_session_shows_shell_title_and_hint(tmp_path):
    agent = FakeAgent()
    console = RecordingConsole()
    session = ChatSession(
        agent=agent,
        config=AsenConfig(workspace=tmp_path),
        console=console,
        input_reader=FakeInputReader(["/exit"]),
        shell_runner=FakeShellRunner(),
        session_mode="shell",
    )

    await session.run()

    assert console.events[0] == ("title", "shell")
    assert console.events[1][0] == "info"
    assert "Shell mode enabled" in console.events[1][1]
