from asen_cli.core.llm import _messages_with_tool_instructions


def test_messages_with_tool_instructions_adds_tool_schema_to_system_prompt():
    messages = [{"role": "system", "content": "base system"}]
    tools = [
        {
            "name": "write_file",
            "description": "Write a file",
            "arguments": {"path": "file path", "content": "file content"},
        }
    ]

    updated = _messages_with_tool_instructions(messages, tools)

    assert updated[0]["role"] == "system"
    assert "base system" in updated[0]["content"]
    assert "write_file" in updated[0]["content"]
    assert "exactly the asen JSON protocol" in updated[0]["content"]
    assert messages[0]["content"] == "base system"
