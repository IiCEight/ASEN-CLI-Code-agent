from asen_cli.config import load_config


def test_load_config_from_yaml_and_env(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "model: yaml-model\nworkspace: ./demo\nmax_steps: 3\nrequire_approval: false\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ASEN_MODEL", "env-model")
    monkeypatch.setenv("ASEN_MAX_STEPS", "5")

    cfg = load_config(config_path)

    assert cfg.model == "env-model"
    assert cfg.max_steps == 5
    assert cfg.require_approval is False
    assert cfg.workspace == (tmp_path / "demo").resolve()


def test_workspace_cli_override_wins(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("workspace: ./from-yaml\n", encoding="utf-8")

    cfg = load_config(config_path, workspace=tmp_path / "from-cli")

    assert cfg.workspace == (tmp_path / "from-cli").resolve()


def test_load_config_from_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "ASEN_API_KEY=sk-from-dotenv\n"
        "ASEN_BASE_URL=https://example.test/v1\n"
        "ASEN_MODEL=dotenv-model\n"
        "ASEN_MAX_CONTEXT_TOKENS=12000\n"
        "ASEN_RESERVE_OUTPUT_TOKENS=1500\n"
        "ASEN_REQUIRE_APPROVAL=false\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    cfg = load_config()

    assert cfg.api_key == "sk-from-dotenv"
    assert cfg.base_url == "https://example.test/v1"
    assert cfg.model == "dotenv-model"
    assert cfg.max_context_tokens == 12000
    assert cfg.reserve_output_tokens == 1500
    assert cfg.require_approval is False
