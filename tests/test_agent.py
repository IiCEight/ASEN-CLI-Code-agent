import pytest

from asen_cli.config import AsenConfig
from asen_cli.core.agent import Agent, AgentEvents, parse_agent_response
from asen_cli.tools.file import ReadFileTool, WriteFileTool
from asen_cli.tools.registry import ToolRegistry


class FakeLlm:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, messages, tools):
        self.calls.append((messages, tools))
        return self.responses.pop(0)


def test_parse_final_response():
    parsed = parse_agent_response('{"final": "done"}')
    assert parsed.final_text == "done"
    assert parsed.tool_calls == []


def test_parse_tool_call_response():
    parsed = parse_agent_response(
        '{"tool_calls":[{"name":"read_file","arguments":{"path":"hello.txt"}}]}'
    )
    assert parsed.tool_calls[0].name == "read_file"
    assert parsed.tool_calls[0].arguments == {"path": "hello.txt"}


def test_parse_plan_response():
    parsed = parse_agent_response(
        '{"plan":[{"id":"1","content":"Inspect project"},"Read files"]}'
    )

    assert parsed.plan_steps[0].id == "1"
    assert parsed.plan_steps[0].content == "Inspect project"
    assert parsed.plan_steps[0].status == "pending"
    assert parsed.plan_steps[1].id == "2"
    assert parsed.plan_steps[1].content == "Read files"


def test_parse_plain_text_response_is_invalid():
    parsed = parse_agent_response("I would write print('Hello, World!') to helloworld.py")

    assert parsed.invalid_reason == "response was not a JSON object"
    assert parsed.final_text is None
    assert parsed.tool_calls == []


@pytest.mark.asyncio
async def test_agent_returns_final_answer(tmp_path):
    llm = FakeLlm(['{"final": "hello"}'])
    agent = Agent(
        config=AsenConfig(workspace=tmp_path),
        llm=llm,
        tools=ToolRegistry([]),
        system_prompt="system",
    )

    result = await agent.run("say hi")

    assert result == "hello"


@pytest.mark.asyncio
async def test_agent_executes_tool_then_returns_final(tmp_path):
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    llm = FakeLlm(
        [
            '{"tool_calls":[{"name":"read_file","arguments":{"path":"hello.txt"}}]}',
            '{"final": "file says hello"}',
        ]
    )
    registry = ToolRegistry([ReadFileTool(tmp_path, max_file_bytes=100)])
    agent = Agent(
        config=AsenConfig(workspace=tmp_path, max_steps=3),
        llm=llm,
        tools=registry,
        system_prompt="system",
    )

    result = await agent.run("read file")

    assert result == "file says hello"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_agent_accepts_plan_then_executes_steps(tmp_path):
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    events = []
    llm = FakeLlm(
        [
            '{"plan":[{"id":"1","content":"Read hello.txt"}]}',
            '{"tool_calls":[{"name":"read_file","arguments":{"path":"hello.txt"}}]}',
            '{"final":"done"}',
        ]
    )
    agent = Agent(
        config=AsenConfig(workspace=tmp_path, max_steps=4),
        llm=llm,
        tools=ToolRegistry([ReadFileTool(tmp_path, max_file_bytes=100)]),
        system_prompt="system",
        events=AgentEvents(
            on_plan=lambda steps: events.append(("plan", [step.content for step in steps])),
            on_plan_step=lambda step: events.append(("plan_step", step.id, step.status)),
        ),
    )

    result = await agent.run("read file")

    assert result == "done"
    assert len(llm.calls) == 3
    assert ("plan", ["Read hello.txt"]) in events
    assert ("plan_step", "1", "in_progress") in events
    assert ("plan_step", "1", "completed") in events
    assert "Plan accepted" in llm.calls[1][0][-1]["content"]


@pytest.mark.asyncio
async def test_agent_marks_plan_step_failed_on_tool_error(tmp_path):
    events = []
    llm = FakeLlm(
        [
            '{"plan":[{"id":"1","content":"Read missing file"}]}',
            '{"tool_calls":[{"name":"read_file","arguments":{}}]}',
            '{"final":"blocked"}',
        ]
    )
    agent = Agent(
        config=AsenConfig(workspace=tmp_path, max_steps=4),
        llm=llm,
        tools=ToolRegistry([ReadFileTool(tmp_path, max_file_bytes=100)]),
        system_prompt="system",
        events=AgentEvents(
            on_plan_step=lambda step: events.append((step.id, step.status)),
        ),
    )

    result = await agent.run("read file")

    assert result == "blocked"
    assert ("1", "failed") in events
    assert "validation_error" in llm.calls[2][0][-1]["content"]


@pytest.mark.asyncio
async def test_agent_feedback_allows_tool_argument_retry(tmp_path):
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    llm = FakeLlm(
        [
            '{"tool_calls":[{"name":"read_file","arguments":{}}]}',
            '{"tool_calls":[{"name":"read_file","arguments":{"path":"hello.txt"}}]}',
            '{"final": "recovered"}',
        ]
    )
    agent = Agent(
        config=AsenConfig(workspace=tmp_path, max_steps=4),
        llm=llm,
        tools=ToolRegistry([ReadFileTool(tmp_path, max_file_bytes=100)]),
        system_prompt="system",
    )

    result = await agent.run("read file")

    assert result == "recovered"
    assert len(llm.calls) == 3
    assert "validation_error" in llm.calls[1][0][-1]["content"]
    assert "correct the tool name or arguments" in llm.calls[1][0][-1]["content"]


@pytest.mark.asyncio
async def test_agent_emits_progress_events(tmp_path):
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    events = []
    llm = FakeLlm(
        [
            '{"tool_calls":[{"name":"read_file","arguments":{"path":"hello.txt"}}]}',
            '{"final": "done"}',
        ]
    )
    agent = Agent(
        config=AsenConfig(workspace=tmp_path, max_steps=3),
        llm=llm,
        tools=ToolRegistry([ReadFileTool(tmp_path, max_file_bytes=100)]),
        system_prompt="system",
        events=AgentEvents(
            on_thinking=lambda step: events.append(("thinking", step)),
            on_llm_response=lambda raw: events.append(("raw", raw)),
            on_tool_call=lambda name, args: events.append(("tool_call", name, args)),
            on_tool_result=lambda name, rendered: events.append(("tool_result", name, rendered)),
        ),
    )

    result = await agent.run("read file")

    assert result == "done"
    assert ("thinking", 1) in events
    assert any(event[0] == "raw" for event in events)
    assert ("tool_call", "read_file", {"path": "hello.txt"}) in events
    assert ("tool_result", "read_file", "hello") in events


@pytest.mark.asyncio
async def test_agent_retries_invalid_plain_text_response(tmp_path):
    llm = FakeLlm(
        [
            "Save this as helloworld.py:\n```python\nprint('Hello, World!')\n```",
            '{"tool_calls":[{"name":"write_file","arguments":'
            '{"path":"helloworld.py","content":"print(\\"Hello, World!\\")\\n"}}]}',
            '{"final": "created helloworld.py"}',
        ]
    )
    registry = ToolRegistry([WriteFileTool(tmp_path, require_approval=False)])
    agent = Agent(
        config=AsenConfig(workspace=tmp_path, max_steps=4),
        llm=llm,
        tools=registry,
        system_prompt="system",
    )

    result = await agent.run("帮我写一个helloworld.py")

    assert result == "created helloworld.py"
    assert (tmp_path / "helloworld.py").read_text(encoding="utf-8") == 'print("Hello, World!")\n'
    assert len(llm.calls) == 3
    assert "could not be used" in llm.calls[1][0][-1]["content"]


@pytest.mark.asyncio
async def test_agent_stops_at_max_steps(tmp_path):
    llm = FakeLlm(['{"tool_calls":[{"name":"missing","arguments":{}}]}'] * 3)
    agent = Agent(
        config=AsenConfig(workspace=tmp_path, max_steps=2),
        llm=llm,
        tools=ToolRegistry([]),
        system_prompt="system",
    )

    result = await agent.run("loop")

    assert "max_steps" in result
