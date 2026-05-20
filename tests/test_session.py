import pytest

from asen_cli.config import AsenConfig
from asen_cli.core.session import ChatSession


class FakeTools:
    def schemas(self):
        return [{"name": "read_file", "description": "Read a file."}]


class FakeAgent:
    def __init__(self):
        self.tools = FakeTools()
        self.calls = []

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


class RecordingConsole:
    def __init__(self):
        self.events = []

    def title(self):
        self.events.append(("title", None))

    def clear(self):
        self.events.append(("clear", None))

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


@pytest.mark.asyncio
async def test_session_handles_slash_commands(tmp_path):
    agent = FakeAgent()
    console = RecordingConsole()
    session = ChatSession(
        agent=agent,
        config=AsenConfig(workspace=tmp_path, api_key="secret"),
        console=console,
        input_reader=FakeInputReader(["/help", "/tools", "/config", "/clear", "/exit"]),
    )

    await session.run()

    kinds = [kind for kind, _ in console.events]
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
    )

    await session.run()

    assert agent.calls == ["line1\nline2"]
