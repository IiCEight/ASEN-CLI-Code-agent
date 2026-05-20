from asen_cli.core.protocol import ChatMessage


def test_tool_message_is_rendered_as_user_message_for_custom_protocol():
    message = ChatMessage(role="tool", name="write_file", content="Wrote file")

    assert message.to_openai() == {
        "role": "user",
        "content": "Tool result from write_file:\nWrote file",
    }
