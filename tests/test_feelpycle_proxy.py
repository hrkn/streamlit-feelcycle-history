import builtins
import os
import pathlib
import sys
import tempfile
import unittest.mock

import pytest

import feelpycle_proxy


def test_get_locked_commit_hash_with_temp_files() -> None:
    # 1. uv.lock から commit を取得できるテスト
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        lock_file = tmp_path / "uv.lock"
        lock_file.write_text(
            """
version = 1
[[package]]
name = "feelpycle"
version = "0.1.0"
source = { git = "https://github.com/hrkn/feelpycle.git", commit = "1234567890abcdef" }
""",
            encoding="utf-8",
        )

        commit = feelpycle_proxy.get_locked_commit_hash(
            package_name="feelpycle", project_root=tmp_path
        )
        assert commit == "1234567890abcdef"


def test_get_locked_commit_hash_with_git_url_hash() -> None:
    # uv.lock の git = "...#<commit_hash>" 形式から取得できるテスト
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        lock_file = tmp_path / "uv.lock"
        lock_file.write_text(
            """
version = 1
[[package]]
name = "feelpycle"
version = "0.1.0"
source = { git = "ssh://git@github.com/hrkn/feelpycle.git#36886d987c2786c64e47bb071e5179dda7ff9663" }
""",
            encoding="utf-8",
        )

        commit = feelpycle_proxy.get_locked_commit_hash(
            package_name="feelpycle", project_root=tmp_path
        )
        assert commit == "36886d987c2786c64e47bb071e5179dda7ff9663"


def test_get_locked_commit_hash_fallback_pyproject() -> None:
    # 2. uv.lock がなく pyproject.toml の sources から取得できるテスト
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        toml_file = tmp_path / "pyproject.toml"
        toml_file.write_text(
            """
[tool.uv.sources]
feelpycle = { git = "git+ssh://git@github.com/hrkn/feelpycle.git", rev = "fedcba0987654321" }
""",
            encoding="utf-8",
        )

        commit = feelpycle_proxy.get_locked_commit_hash(
            package_name="feelpycle", project_root=tmp_path
        )
        assert commit == "fedcba0987654321"


def test_get_locked_commit_hash_none() -> None:
    # 3. どちらのファイルも存在しないか該当パッケージが無い場合
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        commit = feelpycle_proxy.get_locked_commit_hash(
            package_name="unknown_package", project_root=tmp_path
        )
        assert commit is None


def test_ensure_installed_already_available() -> None:
    # 既にインストールされている場合は何もしない
    feelpycle_proxy.ensure_installed()


def test_ensure_installed_triggers_install_with_commit() -> None:
    orig_import = builtins.__import__

    def mock_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "feelpycle.api":
            raise ModuleNotFoundError(f"No module named '{name}'")
        return orig_import(name, *args, **kwargs)

    with (
        unittest.mock.patch("builtins.__import__", side_effect=mock_import),
        unittest.mock.patch.dict(os.environ, {"GITHUB_TOKEN": "test_token_123"}),
        unittest.mock.patch(
            "feelpycle_proxy.get_locked_commit_hash", return_value="commithash456"
        ),
        unittest.mock.patch("subprocess.check_call") as mock_check_call,
    ):
        feelpycle_proxy.ensure_installed()
        mock_check_call.assert_called_once()
        cmd = mock_check_call.call_args[0][0]
        assert any(
            "git+https://test_token_123@github.com/hrkn/feelpycle.git@commithash456"
            in str(arg)
            for arg in cmd
        )


def test_ensure_installed_no_token_raises() -> None:
    orig_import = builtins.__import__

    def mock_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "feelpycle.api":
            raise ModuleNotFoundError(f"No module named '{name}'")
        return orig_import(name, *args, **kwargs)

    env_without_token = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}

    with (
        unittest.mock.patch("builtins.__import__", side_effect=mock_import),
        unittest.mock.patch.dict(os.environ, env_without_token, clear=True),
    ):
        with pytest.raises(RuntimeError, match="GITHUB_TOKEN を設定してください"):
            feelpycle_proxy.ensure_installed()


def test_run_install_uses_uv_when_available() -> None:
    with (
        unittest.mock.patch("shutil.which", return_value="/usr/local/bin/uv"),
        unittest.mock.patch("subprocess.check_call") as mock_check_call,
    ):
        feelpycle_proxy._run_install("git+https://example.com/repo.git")
        mock_check_call.assert_called_once_with(
            ["/usr/local/bin/uv", "pip", "install", "git+https://example.com/repo.git"]
        )


def test_run_install_fallback_to_pip() -> None:
    with (
        unittest.mock.patch("shutil.which", return_value=None),
        unittest.mock.patch("pathlib.Path.is_file", return_value=False),
        unittest.mock.patch("subprocess.check_call") as mock_check_call,
    ):
        feelpycle_proxy._run_install("git+https://example.com/repo.git")
        mock_check_call.assert_called_once_with(
            [sys.executable, "-m", "pip", "install", "git+https://example.com/repo.git"]
        )
