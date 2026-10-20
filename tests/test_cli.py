import json
import os
import stat
import subprocess
import sys


def run_cli(*args, check=True):
    cmd = [sys.executable, "-m", "ai_usage_collector.cli", *args]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(
            f"Command failed with code {res.returncode}:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"
        )
    return res


def test_cli_refresh_creates_config_and_cache(tmp_path):
    config_dir = tmp_path / "config"
    config_path = config_dir / "config.json"
    cache_dir = tmp_path / "cache"
    cache_path = cache_dir / "status.json"

    res = run_cli(
        "--refresh",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    )
    assert res.returncode == 0

    # Verify config file exists and has 0600 permissions
    assert config_path.exists()
    config_mode = stat.S_IMODE(os.stat(config_path).st_mode)
    assert config_mode == 0o600, f"Expected 0600, got {oct(config_mode)}"

    # Verify config dir exists and has 0700 permissions
    config_dir_mode = stat.S_IMODE(os.stat(config_dir).st_mode)
    assert config_dir_mode == 0o700, f"Expected 0700, got {oct(config_dir_mode)}"

    # Verify status.json exists
    assert cache_path.exists()
    with open(cache_path, "r", encoding="utf-8") as f:
        status_data = json.load(f)

    assert status_data["version"] == 2
    assert "last_updated" in status_data
    assert "agents" in status_data
    assert "claude" in status_data["agents"]
    assert "codex" in status_data["agents"]
    assert "gemini" in status_data["agents"]


def test_cli_status_prints_to_stdout(tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    # Pre-populate status.json
    dummy_status = {
        "version": 1,
        "last_updated": "2026-10-20T10:00:00Z",
        "status": "ok",
        "agents": {
            "claude": {"name": "Claude", "status": "ok", "accounts": []},
            "codex": {"name": "Codex", "status": "ok", "accounts": []},
            "gemini": {"name": "Gemini", "status": "ok", "accounts": []},
        },
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(dummy_status, f)

    res = run_cli(
        "--status",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    )
    assert res.returncode == 0
    output_json = json.loads(res.stdout)
    assert output_json["version"] == 1
    assert output_json["last_updated"] == "2026-10-20T10:00:00Z"


def test_cli_refresh_and_status_combined(tmp_path):
    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    res = run_cli(
        "--refresh",
        "--status",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    )
    assert res.returncode == 0
    output_json = json.loads(res.stdout)
    assert output_json["version"] == 2
    assert "last_updated" in output_json
    assert "agents" in output_json
    assert cache_path.exists()


def test_cli_installed_entrypoint(tmp_path):
    # Test that the entrypoint executable ai-usage-collector in .venv/bin works
    venv_bin = os.path.join(os.path.dirname(sys.executable), "ai-usage-collector")
    if not os.path.exists(venv_bin):
        # Entrypoint might be named differently or in path
        return

    config_path = tmp_path / "config.json"
    cache_path = tmp_path / "status.json"

    cmd = [
        venv_bin,
        "--refresh",
        "--status",
        "--config-path", str(config_path),
        "--cache-path", str(cache_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["version"] == 2
