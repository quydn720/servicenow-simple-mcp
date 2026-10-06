from servicenow_mcp.config.environment import environment_file, load_environment


def test_environment_files_default_to_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MCP_ENV_FILE", raising=False)
    monkeypatch.delenv("MCP_REMOTE_ENV_FILE", raising=False)
    assert environment_file() == tmp_path / ".env"
    assert environment_file(remote=True) == tmp_path / ".env.remote"


def test_explicit_environment_files_and_existing_values(tmp_path, monkeypatch):
    local = tmp_path / "local.env"
    remote = tmp_path / "remote.env"
    local.write_text("MCP_TEST_SETTING=local\n")
    remote.write_text("MCP_TEST_SETTING=remote\n")
    monkeypatch.setenv("MCP_ENV_FILE", str(local))
    monkeypatch.setenv("MCP_REMOTE_ENV_FILE", str(remote))
    monkeypatch.delenv("MCP_TEST_SETTING", raising=False)
    assert environment_file() == local
    assert environment_file(remote=True) == remote
    # Track dotenv writes so pytest restores the environment after this test.
    monkeypatch.setenv("MCP_TEST_SETTING", "")
    monkeypatch.delenv("MCP_TEST_SETTING")
    load_environment()
    import os

    assert os.environ["MCP_TEST_SETTING"] == "local"
    load_environment(remote=True)
    assert os.environ["MCP_TEST_SETTING"] == "local"
    monkeypatch.delenv("MCP_TEST_SETTING")
    load_environment(remote=True)
    assert os.environ["MCP_TEST_SETTING"] == "remote"
