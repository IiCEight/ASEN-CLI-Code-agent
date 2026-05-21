from asen_cli.core.checkpoint_store import CheckpointStore, resolve_checkpoint_dir


def test_checkpoint_store_can_list_and_render_diff(tmp_path):
    store = CheckpointStore.create_file_checkpoint(
        tmp_path,
        tool_name="write_file",
        path=tmp_path / "hello.py",
        before="print('old')\n",
        after="print('new')\n",
    )

    assert store is not None
    assert len(CheckpointStore.list(tmp_path)) == 1
    assert resolve_checkpoint_dir(tmp_path, store.checkpoint_id[:12]) is not None

    reopened = CheckpointStore.open(tmp_path, store.checkpoint_id)
    diff_text = reopened.render_diff()
    assert "-print('old')" in diff_text
    assert "+print('new')" in diff_text


def test_checkpoint_restore_restores_existing_file(tmp_path):
    target = tmp_path / "hello.py"
    target.write_text("print('new')\n", encoding="utf-8")
    store = CheckpointStore.create_file_checkpoint(
        tmp_path,
        tool_name="replace_in_file",
        path=target,
        before="print('old')\n",
        after="print('new')\n",
    )

    assert store is not None
    actions = store.restore()

    assert target.read_text(encoding="utf-8") == "print('old')\n"
    assert actions == ["Restored hello.py"]


def test_checkpoint_restore_removes_created_file(tmp_path):
    target = tmp_path / "created.py"
    target.write_text("print('hello')\n", encoding="utf-8")
    store = CheckpointStore.create_file_checkpoint(
        tmp_path,
        tool_name="write_file",
        path=target,
        before=None,
        after="print('hello')\n",
    )

    assert store is not None
    actions = store.restore()

    assert not target.exists()
    assert actions == ["Removed created.py"]
