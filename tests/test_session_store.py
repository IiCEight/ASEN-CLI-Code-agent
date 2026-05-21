from asen_cli.config import AsenConfig
from asen_cli.core.context_manager import ContextManager
from asen_cli.core.session_store import SessionStore, build_final_summary, resolve_session_dir
from asen_cli.core.token_budget import TokenBudget


def _manager() -> ContextManager:
    return ContextManager(
        "system",
        token_budget=TokenBudget(max_context_tokens=4_000, reserve_output_tokens=500),
    )


def test_session_store_can_snapshot_and_restore_context(tmp_path):
    store = SessionStore.create(
        AsenConfig(workspace=tmp_path, provider="openai", model="demo-model"),
        session_mode="chat",
        session_id="demo-session",
    )
    manager = _manager()
    manager.add_user("first question")
    manager.add_assistant("first answer")
    manager.add_tool("shell", "exit_code=0\nall good")

    store.record_user_message("first question")
    store.record_assistant_message("first answer")
    store.record_snapshot(manager, final_text="first answer")

    snapshot = store.latest_snapshot()
    assert snapshot is not None

    restored = _manager()
    restored.load_snapshot(snapshot)

    assert restored.messages[-1].content == "exit_code=0\nall good"
    assert restored.latest_assistant_message() == "first answer"


def test_session_store_list_and_prefix_lookup(tmp_path):
    SessionStore.create(
        AsenConfig(workspace=tmp_path, provider="openai", model="demo-model"),
        session_mode="chat",
        session_id="2026-05-21-demo",
    )

    sessions = SessionStore.list(tmp_path)
    assert len(sessions) == 1
    assert sessions[0].session_id == "2026-05-21-demo"
    assert resolve_session_dir(tmp_path, "2026-05-21") is not None


def test_build_final_summary_prefers_edits_and_latest_answer():
    manager = _manager()
    manager.add_assistant("Implemented session resume.")
    manager.remember_fact("File edit: Updated app.py with session commands")
    manager.remember_fact("File edit: Added session_store.py")

    summary = build_final_summary(manager)

    assert "Recent file edits" in summary
    assert "Updated app.py with session commands" in summary
    assert "Latest assistant answer" in summary
