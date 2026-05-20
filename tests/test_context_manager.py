from asen_cli.core.context_manager import ContextManager, compress_tool_result, render_plan
from asen_cli.core.protocol import PlanStep
from asen_cli.core.token_budget import TokenBudget


def test_token_budget_estimates_messages():
    budget = TokenBudget(max_context_tokens=100, reserve_output_tokens=20)

    assert budget.input_budget == 80
    assert budget.estimate_text_tokens("hello world") > 0


def test_context_manager_keeps_summary_facts_plan_and_recent_messages():
    manager = ContextManager(
        "system",
        token_budget=TokenBudget(max_context_tokens=800, reserve_output_tokens=100),
        max_recent_messages=4,
        max_tool_result_chars=200,
    )
    manager.add_user("original task")
    manager.set_plan([PlanStep(id="1", content="Read files", status="pending")])
    for index in range(8):
        manager.add_assistant(f"assistant message {index}")

    messages = manager.as_openai_messages()
    contents = "\n".join(message["content"] for message in messages)

    assert messages[0]["role"] == "system"
    assert "Conversation summary" in contents
    assert "Key facts" in contents
    assert "Current plan" in contents
    assert "assistant message 7" in contents
    assert manager.summary is not None


def test_context_manager_compresses_large_tool_result_and_remembers_fact():
    manager = ContextManager(
        "system",
        token_budget=TokenBudget(max_context_tokens=2_000, reserve_output_tokens=100),
        max_recent_messages=8,
        max_tool_result_chars=500,
    )
    manager.add_tool("read_file", "x" * 3_000)

    messages = manager.as_openai_messages()
    contents = "\n".join(message["content"] for message in messages)

    assert "compressed tool result" in contents
    assert "original_chars=3000" in contents


def test_context_manager_remembers_edit_fact():
    manager = ContextManager(
        "system",
        token_budget=TokenBudget(max_context_tokens=2_000, reserve_output_tokens=100),
    )

    manager.add_tool("replace_in_file", "Applied edit to /tmp/demo.py. Snapshot saved.")

    assert any(fact.startswith("File edit:") for fact in manager.facts)


def test_compress_tool_result_keeps_small_result():
    assert compress_tool_result("read_file", "small", 100) == "small"


def test_render_plan_outputs_statuses():
    rendered = render_plan([PlanStep(id="1", content="Do it", status="in_progress")])

    assert "[in_progress] 1. Do it" in rendered
