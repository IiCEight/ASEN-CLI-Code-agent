from typer.testing import CliRunner

from asen_cli.app import app

runner = CliRunner()


def test_config_init_set_get_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    init_result = runner.invoke(app, ["config", "init"])
    assert init_result.exit_code == 0
    assert (tmp_path / ".asen" / "config.yaml").exists()

    set_result = runner.invoke(app, ["config", "set", "model", "cli-model"])
    assert set_result.exit_code == 0

    get_result = runner.invoke(app, ["config", "get", "model"])
    assert get_result.exit_code == 0
    assert "cli-model" in get_result.output


def test_config_set_global(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["config", "set", "model", "global-model", "--global"])

    assert result.exit_code == 0
    assert "global-model" in (home / ".asen" / "config.yaml").read_text(encoding="utf-8")


def test_config_get_masks_api_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / ".asen"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("api_key: sk-secret\n", encoding="utf-8")

    result = runner.invoke(app, ["config", "get"])

    assert result.exit_code == 0
    assert "***" in result.output
    assert "sk-secret" not in result.output
