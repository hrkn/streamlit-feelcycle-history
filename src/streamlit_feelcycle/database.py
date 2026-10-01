import logging
import os
import queue
import re
import threading
import time

import dotenv
import httpx
import requests
import sqlalchemy
import sqlalchemy.event
import streamlit as st

LOGGER = logging.getLogger(__name__)

# .envファイルをロード
dotenv.load_dotenv()

# 1. 環境変数から接続URLを構築
ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
DATABASE_ID = os.environ.get("CLOUDFLARE_DATABASE_ID")

if not all([ACCOUNT_ID, API_TOKEN, DATABASE_ID]):
    st.error("必要な環境変数が設定されていません。.envファイルを確認してください。")
    st.stop()


# 同期キューと同期中フラグ
@st.cache_resource
def get_sync_queue() -> queue.Queue:
    return queue.Queue()


sync_queue = get_sync_queue()
_sync_in_progress = threading.local()


def get_local_engine() -> sqlalchemy.Engine:
    db_path = os.environ.get("LOCAL_DB_PATH", ".streamlit/.local.sqlite")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    engine = sqlalchemy.create_engine(f"sqlite:///{db_path}", echo=False)
    return engine


get_local_engine = st.cache_resource(get_local_engine)
local_engine = get_local_engine()


# 3. データ初期ダウンロードとスキーマ作成
def download_db(local_eng: sqlalchemy.Engine) -> None:
    _sync_in_progress.active = True
    LOGGER.debug("Starting D1 database download via export API...")
    try:
        # 直接 D1 export API に POST
        default_base = (
            f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}"
            f"/d1/database/{DATABASE_ID}"
        )
        base_url = os.environ.get("CF_D1_BASE_URL", default_base)
        headers = {
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
        }
        url = f"{base_url}/export"

        response = requests.post(
            url, headers=headers, json={"output_format": "file"}, timeout=15.0
        )
        response.raise_for_status()

        data = response.json()
        if not data.get("success", False):
            errors = data.get("errors", [])
            err_msg = (
                errors[0].get("message", "Unknown error")
                if errors
                else "Unknown D1 export error"
            )
            raise RuntimeError(f"D1 export failed: {err_msg}")

        result = data.get("result", {})
        sql_content = result.get("sql")

        # signed_urlがあればrequestsでダウンロード
        signed_url = result.get("signed_url")
        if signed_url:
            LOGGER.debug(f"Downloading SQL dump from signed URL: {signed_url}")
            dl_res = requests.get(signed_url, timeout=30.0)
            dl_res.raise_for_status()
            sql_content = dl_res.text

        if not sql_content:
            raise RuntimeError("D1 export returned empty SQL content")

        LOGGER.debug(
            "D1 database SQL dump downloaded successfully. Restoring to local SQLite..."
        )

        # ローカルDBをクリアしてダンプを実行
        raw_conn = local_eng.raw_connection()
        try:
            raw_conn.execute("PRAGMA foreign_keys = OFF;")
            cursor = raw_conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            tables = [row[0] for row in cursor.fetchall()]
            for table in tables:
                cursor.execute(f'DROP TABLE IF EXISTS "{table}";')

            raw_conn.executescript(sql_content)
            raw_conn.commit()
            LOGGER.debug("Local SQLite database restored successfully.")
        finally:
            raw_conn.close()

    except Exception as e:
        LOGGER.error(f"Failed to download/restore D1 database: {e}")
        raise e
    finally:
        _sync_in_progress.active = False


# 4. SQLAlchemy Eventによるフック
def after_cursor_execute(
    conn, cursor, statement, parameters, context, executemany
) -> None:
    # 初期ロードや同期処理中の書き込みはフックしない
    if getattr(_sync_in_progress, "active", False):
        return

    # SELECT やメタデータ読み取りクエリは無視
    stmt_upper = statement.strip().upper()
    if stmt_upper.startswith(("SELECT", "PRAGMA", "SHOW")):
        return

    # テーブル名とプライマリキーの特定
    table_name = "unknown"
    pk_value = "unknown"

    try:
        # テーブル名の抽出
        table_match = re.search(
            r'(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+["`]?(\w+)["`]?',
            statement,
            re.IGNORECASE,
        )
        if table_match:
            table_name = table_match.group(1)

        # プライマリキー値の抽出
        if stmt_upper.startswith("INSERT"):
            pk_value = cursor.lastrowid
        elif "WHERE" in stmt_upper:
            if parameters:
                if executemany:
                    pk_list = []
                    for param in parameters:
                        pk_list.append(
                            param[-1] if hasattr(param, "__getitem__") else param
                        )
                    pk_value = pk_list
                else:
                    pk_value = parameters[-1]
    except Exception as e:
        LOGGER.warning(f"Failed to parse table/PK from statement: {e}")

    # ログ出力
    LOGGER.debug(
        f"SQLAlchemy Event Hooked: Table={table_name}, PrimaryKey={pk_value}, SQL={statement}, Params={parameters}"
    )

    # キューに追加（デバッグ用のメタ情報も含める）
    if executemany:
        for params in parameters:
            params_list = list(params) if params else []
            sync_queue.put(
                {
                    "sql": statement,
                    "params": params_list,
                    "table": table_name,
                    "pk": pk_value,
                }
            )
    else:
        params_list = list(parameters) if parameters else []
        sync_queue.put(
            {
                "sql": statement,
                "params": params_list,
                "table": table_name,
                "pk": pk_value,
            }
        )


# イベントリスナーを重複しないよう登録（st.cache_resourceで維持されるEngineに属性を追加して管理）
if not getattr(local_engine, "_listener_registered", False):
    sqlalchemy.event.listen(local_engine, "after_cursor_execute", after_cursor_execute)
    setattr(local_engine, "_listener_registered", True)


# 5. D1へのバッチ送信処理
def _send_batch(batch: list, log_info_list: list) -> None:
    if not batch:
        return

    # 直接 D1 REST API に POST
    default_base = (
        f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}"
        f"/d1/database/{DATABASE_ID}"
    )
    base_url = os.environ.get("CF_D1_BASE_URL", default_base)
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
    }
    url = f"{base_url}/query"

    LOGGER.debug(
        f"Starting sync of {len(batch)} queries to Remote D1 using persistent connection pool..."
    )
    try:
        with httpx.Client(timeout=10.0) as client:
            for (table, pk, sql), item in zip(log_info_list, batch):
                LOGGER.debug(
                    f"Sending SQL to Remote D1: Table={table}, PrimaryKey={pk}, SQL={sql}"
                )
                response = client.post(url, headers=headers, json=item)
                response.raise_for_status()

                data = response.json()
                if not data.get("success", False):
                    errors = data.get("errors", [])
                    err_msg = (
                        errors[0].get("message", "Unknown error")
                        if errors
                        else "Unknown D1 API error"
                    )
                    print(f"Sync to D1 failed for query {sql}: {err_msg}")
    except Exception as e:
        print(f"Error syncing to D1: {e}")


# テスト用のキュー即時同期ヘルパー
def flush_sync_queue() -> None:
    batch = []
    log_info_list = []
    while not sync_queue.empty():
        try:
            item = sync_queue.get_nowait()
            batch.append({"sql": item["sql"], "params": item["params"]})
            log_info_list.append((item.get("table"), item.get("pk"), item["sql"]))
        except queue.Empty:
            break
    if batch:
        _send_batch(batch, log_info_list)


# 6. バックグラウンド同期スレッドの起動管理
def start_sync_thread() -> threading.Thread:
    def run():
        while True:
            try:
                # キューにデータが入るまでブロックして待つ
                item = sync_queue.get(block=True, timeout=None)

                # 最初の変更をバッチに追加
                batch = [{"sql": item["sql"], "params": item["params"]}]
                log_info_list = [(item.get("table"), item.get("pk"), item["sql"])]

                # 3秒間待機して他の変更を集約する
                time.sleep(3.0)

                # その間に溜まったキューの残りをすべて回収
                while not sync_queue.empty():
                    try:
                        extra_item = sync_queue.get_nowait()
                        batch.append(
                            {
                                "sql": extra_item["sql"],
                                "params": extra_item["params"],
                            }
                        )
                        log_info_list.append(
                            (
                                extra_item.get("table"),
                                extra_item.get("pk"),
                                extra_item["sql"],
                            )
                        )
                    except queue.Empty:
                        break

                # 送信処理
                _send_batch(batch, log_info_list)
            except Exception as e:
                LOGGER.error(f"Error in sync thread loop: {e}")
                time.sleep(1.0)  # エラー発生時の無限ループ防止

    thread = threading.Thread(target=run, daemon=True, name="D1SyncThread")
    thread.start()
    return thread


start_sync_thread = st.cache_resource(start_sync_thread)


@st.cache_resource
def initialize_app_once() -> None:
    download_db(local_engine)
    start_sync_thread()
