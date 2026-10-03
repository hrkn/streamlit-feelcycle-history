import os
import pathlib
import shutil
import subprocess
import sys
import tomllib
import typing


def _run_install(repo_url: str) -> None:
    """パッケージをインストールする。uv pip install、pip、ensurepip の順に試行する。"""
    # 1. uv が利用可能な場合は uv pip install を優先 (SCCやuv環境で高速かつ確実)
    uv_cmd = shutil.which("uv")
    if not uv_cmd:
        candidates = [
            pathlib.Path.home() / ".cargo" / "bin" / "uv",
            pathlib.Path.home() / ".local" / "bin" / "uv",
            pathlib.Path(sys.executable).parent / "uv",
        ]
        for c in candidates:
            if c.is_file():
                uv_cmd = str(c)
                break

    if uv_cmd:
        try:
            subprocess.check_call([uv_cmd, "pip", "install", repo_url])
            return
        except Exception:
            pass

    # 2. python -m pip install を試行
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", repo_url])
        return
    except Exception:
        pass

    # 3. pip が存在しない場合、ensurepip で pip を導入してから再試行
    try:
        import ensurepip

        ensurepip.bootstrap()
        subprocess.check_call([sys.executable, "-m", "pip", "install", repo_url])
        return
    except Exception:
        pass

    # 4. python -m ensurepip サブプロセスを実行して再試行
    try:
        subprocess.check_call([sys.executable, "-m", "ensurepip", "--default-pip"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", repo_url])
        return
    except Exception:
        pass

    # 最終フォールバック
    subprocess.check_call([sys.executable, "-m", "pip", "install", repo_url])


def get_locked_commit_hash(
    package_name: str = "feelpycle", project_root: pathlib.Path | None = None
) -> str | None:
    """uv.lock または pyproject.toml からパッケージのコミットハッシュを取得する。"""
    if project_root is None:
        # src/feelpyclew から2階層上がプロジェクトルート
        project_root = pathlib.Path(__file__).resolve().parents[2]

    # 1. uv.lock を探索
    lock_path = project_root / "uv.lock"
    if lock_path.is_file():
        try:
            with open(lock_path, "rb") as f:
                lock_data = tomllib.load(f)
            for pkg in lock_data.get("package", []):
                if pkg.get("name") == package_name:
                    source = pkg.get("source", {})
                    commit = source.get("commit")
                    if commit:
                        return str(commit)
                    git_url = source.get("git")
                    if isinstance(git_url, str) and "#" in git_url:
                        return git_url.split("#", 1)[1]
        except Exception:
            pass

    # 2. pyproject.toml の [tool.uv.sources] をフォールバック探索
    pyproject_path = project_root / "pyproject.toml"
    if pyproject_path.is_file():
        try:
            with open(pyproject_path, "rb") as f:
                pyproject_data = tomllib.load(f)
            sources = (
                pyproject_data.get("tool", {})
                .get("uv", {})
                .get("sources", {})
                .get(package_name, {})
            )
            rev = sources.get("rev") or sources.get("tag")
            if rev:
                return str(rev)
            git_url = sources.get("git")
            if isinstance(git_url, str) and "#" in git_url:
                return git_url.split("#", 1)[1]
        except Exception:
            pass

    return None


def ensure_installed(package_name: str = "feelpycle") -> None:
    """feelpycle が未インストールの場合は、GitHub PAT とコミットハッシュを用いて動的インストールを行う。"""
    try:
        import feelpycle.api

        return
    except ModuleNotFoundError:
        pass

    token: str | None = None
    st_module: typing.Any = None
    try:
        import streamlit as st

        st_module = st
        try:
            token = st.secrets.get("GITHUB_TOKEN")
        except (KeyError, AttributeError, FileNotFoundError):
            token = None
    except ImportError:
        pass

    if not token:
        token = os.environ.get("GITHUB_TOKEN")

    if not token:
        if st_module is not None:
            try:
                st_module.error(
                    f"{package_name} パッケージが見つかりません。Streamlit Secrets または環境変数に GITHUB_TOKEN を設定してください。"
                )
                st_module.stop()
            except Exception:
                pass
        raise RuntimeError(
            f"{package_name} パッケージが見つかりません。GITHUB_TOKEN を設定してください。"
        )

    commit_hash = get_locked_commit_hash(package_name)
    repo_url = f"git+https://{token}@github.com/hrkn/{package_name}.git"
    if commit_hash:
        repo_url = f"{repo_url}@{commit_hash}"

    if st_module is not None:
        try:
            st_module.info(f"{package_name} パッケージをインストールしています...")
        except Exception:
            pass

    _run_install(repo_url)

    if st_module is not None:
        try:
            st_module.rerun()
        except Exception:
            pass


ensure_installed()

# isort: split
import feelpycle_proxy.api as api

__all__ = ["api", "ensure_installed", "get_locked_commit_hash"]
