import os
import socket
import subprocess
import time

import pytest

PORT = 8787

# main.pyの初期化（環境変数チェック）を通過するためのダミー値
os.environ["CLOUDFLARE_ACCOUNT_ID"] = "test-account-id"
os.environ["CLOUDFLARE_API_TOKEN"] = "test-api-token"
os.environ["CLOUDFLARE_DATABASE_ID"] = "test-database-id"
os.environ["CF_D1_BASE_URL"] = f"http://127.0.0.1:{PORT}"
os.environ["LOCAL_DB_PATH"] = ".streamlit/test_local_d1.db"


def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="session", autouse=True)
def manage_wrangler_dev():
    # ポートがすでに開いている場合は新しく起動しない
    if is_port_open(PORT):
        yield
        return

    # ポートが開いていない場合は npx wrangler dev --port PORT を起動
    if os.name == "nt":
        args = ["cmd.exe", "/c", "npx.cmd", "wrangler", "dev", "--port", str(PORT)]
    else:
        args = ["npx", "wrangler", "dev", "--port", str(PORT)]

    # ログファイルを開く
    stdout_file = open("wrangler_stdout.log", "w")
    stderr_file = open("wrangler_stderr.log", "w")

    process = subprocess.Popen(
        args,
        stdout=stdout_file,
        stderr=stderr_file,
        shell=False,
    )

    # 起動を待つ (最大10秒)
    retries = 20
    started = False
    for _ in range(retries):
        if is_port_open(PORT):
            started = True
            break
        time.sleep(0.5)

    if not started:
        # 起動失敗時はプロセスを終了してエラー
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            process.terminate()
            process.wait()
        raise RuntimeError(f"Failed to start wrangler dev on port {PORT}")

    yield

    # テスト終了時にプロセスをクリーンアップ
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    # ファイルをクローズ
    stdout_file.close()
    stderr_file.close()

    # テスト終了後にローカルDBファイルを削除
    db_file = os.environ.get("LOCAL_DB_PATH")
    if db_file and os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass
