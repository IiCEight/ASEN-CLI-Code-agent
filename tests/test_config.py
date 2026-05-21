import pytest

from asen_cli.config import (
    ConfigError,
    get_config_path,
    init_config_file,
    load_config,
    read_config_file,
    set_config_value,
)


def test_layered_config_precedence(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ASEN_MODEL", "env-model")
    monkeypatch.setenv("ASEN_MAX_STEPS", "3")

    global_config = home / ".asen" / "config.yaml"
    global_config.parent.mkdir(parents=True)
    global_config.write_text("model: global-model\nmax_steps: 4\n", encoding="utf-8")

    project_config = tmp_path / ".asen" / "config.yaml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text("model: project-model\nmax_steps: 5\n", encoding="utf-8")

    explicit_config = tmp_path / "explicit.yaml"
    explicit_config.write_text("model: explicit-model\nmax_steps: 6\n", encoding="utf-8")

    cfg = load_config(explicit_config, workspace=tmp_path / "workspace")

    assert cfg.model == "explicit-model"
    assert cfg.max_steps == 6
    assert cfg.workspace == (tmp_path / "workspace").resolve()


def test_project_config_wins_over_global_and_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ASEN_MODEL", "env-model")

    global_config = home / ".asen" / "config.yaml"
    global_config.parent.mkdir(parents=True)
    global_config.write_text("model: global-model\n", encoding="utf-8")

    project_config = tmp_path / ".asen" / "config.yaml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text("model: project-model\n", encoding="utf-8")

    cfg = load_config()

    assert cfg.model == "project-model"


def test_env_is_loaded_when_no_yaml_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ASEN_PROVIDER", "deepseek")
    monkeypatch.setenv("ASEN_MODEL", "env-model")
    monkeypatch.setenv("ASEN_MAX_CONTEXT_TOKENS", "12000")
    monkeypatch.setenv("ASEN_RESERVE_OUTPUT_TOKENS", "1500")

    cfg = load_config()

    assert cfg.model == "env-model"
    assert cfg.max_context_tokens == 12000
    assert cfg.reserve_output_tokens == 1500


def test_dotenv_is_loaded(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "ASEN_API_KEY=sk-from-dotenv\n"
        "ASEN_BASE_URL=https://example.test/v1\n"
        "ASEN_MODEL=dotenv-model\n"
        "ASEN_REQUIRE_APPROVAL=false\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    cfg = load_config()

    assert cfg.api_key == "sk-from-dotenv"
    assert cfg.base_url == "https://example.test/v1"
    assert cfg.model == "dotenv-model"
    assert cfg.require_approval is False


def test_get_config_path_uses_home_and_cwd(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)

    assert get_config_path("global") == home / ".asen" / "config.yaml"
    assert get_config_path("project") == tmp_path / ".asen" / "config.yaml"


def test_init_config_file_creates_template(tmp_path):
    target = tmp_path / ".asen" / "config.yaml"

    created = init_config_file(target)
    data = read_config_file(created)

    assert created == target.resolve()
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o-mini"
    assert data["base_url"] == "https://api.openai.com/v1"


def test_init_config_file_refuses_existing_without_force(tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text("model: old\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        init_config_file(target)


def test_set_config_value_writes_yaml_and_coerces_types(tmp_path):
    target = tmp_path / ".asen" / "config.yaml"

    set_config_value(target, "model", "gpt-test")
    set_config_value(target, "max_steps", "12")
    set_config_value(target, "require_approval", "false")
    data = read_config_file(target)

    assert data["model"] == "gpt-test"
    assert data["max_steps"] == 12
    assert data["require_approval"] is False


def test_set_config_value_rejects_unknown_key(tmp_path):
    with pytest.raises(ConfigError):
        set_config_value(tmp_path / "config.yaml", "missing", "value")
