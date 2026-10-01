import os
import time
import unittest.mock

import pytest
import sqlalchemy
import sqlalchemy.orm

import streamlit_feelcycle.database as db
import streamlit_feelcycle.model as model

_d1_engine = None


def get_d1_engine() -> sqlalchemy.Engine:
    global _d1_engine
    if _d1_engine is None:
        database_url = (
            f"cloudflare_d1://{db.ACCOUNT_ID}:{db.API_TOKEN}@{db.DATABASE_ID}"
        )
        _d1_engine = sqlalchemy.create_engine(database_url, echo=False)
    return _d1_engine


@pytest.fixture(autouse=True)
def mock_env():
    yield
    # エンジン接続を破棄
    try:
        get_d1_engine().dispose()
        db.get_local_engine().dispose()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def db_reset():
    # 各テストの実行前にデータベースをクリーンアップして初期化する
    d1_engine = get_d1_engine()
    local_engine = db.get_local_engine()

    # D1 (Mock Server) 側の初期化
    model.Base.metadata.drop_all(d1_engine)
    model.Base.metadata.create_all(d1_engine)
    with sqlalchemy.orm.Session(d1_engine) as session:
        member1 = model.Member(name="Alice")
        member2 = model.Member(name="Bob")
        session.add_all([member1, member2])
        session.flush()

        web_account1 = model.WebAccount(
            email="alice@example.com", member_id=member1.id, icon=""
        )
        web_account2 = model.WebAccount(
            email="bob@example.com", member_id=member2.id, icon=""
        )
        session.add_all([web_account1, web_account2])
        session.commit()

    # ローカル DB (test_local_d1.db) のファイルを物理削除する
    db_file = os.environ.get("LOCAL_DB_PATH", "test_local_d1.db")
    if os.path.exists(db_file):
        try:
            local_engine.dispose()
            os.remove(db_file)
        except Exception:
            pass

    # ローカル DB をダウンロードして初期化
    db.download_db(local_engine)

    yield


def test_empty_batch_coverage() -> None:
    # _send_batch が空の場合の早期リターンをカバー
    db._send_batch([], [])


def test_executemany_coverage() -> None:
    # executemany のルートをカバー
    local_engine = db.get_local_engine()
    # executemany を発生させるため、直接 raw execute を使用
    with local_engine.begin() as conn:
        conn.execute(
            sqlalchemy.text('INSERT INTO "members" (name) VALUES (:name)'),
            [
                {"name": "MemberA"},
                {"name": "MemberB"},
            ],
        )
    # キューをクリアしておく
    db.flush_sync_queue()


def test_sync_thread_coverage() -> None:
    # start_sync_thread が機能することを簡易的にテスト
    thread = db.start_sync_thread()
    assert thread.is_alive()

    # キューに入れる
    db.sync_queue.put(
        {
            "sql": 'INSERT INTO "members" (name) VALUES (?)',
            "params": ["MemberC"],
            "table": "members",
            "pk": 3,
        }
    )
    # スレッドが 3秒スリープ + 送信するのを少し待つ
    time.sleep(3.5)


def test_download_db_failures() -> None:
    # download_db 関数の異常系テスト
    local_engine = db.get_local_engine()

    # 1. D1 APIレスポンスの success が False の場合
    mock_response = unittest.mock.MagicMock()
    mock_response.json.return_value = {
        "success": False,
        "errors": [{"message": "Mocked API Error"}],
    }
    mock_response.raise_for_status = unittest.mock.MagicMock()

    with unittest.mock.patch("requests.post", return_value=mock_response):
        with pytest.raises(RuntimeError, match="D1 export failed: Mocked API Error"):
            db.download_db(local_engine)

    # 2. signed_url が提供された場合のダウンロード処理
    mock_post_res = unittest.mock.MagicMock()
    mock_post_res.json.return_value = {
        "success": True,
        "result": {
            "signed_url": "http://mock-signed-url.com/dump.sql",
        },
    }
    mock_get_res = unittest.mock.MagicMock()
    mock_get_res.text = "CREATE TABLE dummy (id INTEGER);"
    mock_get_res.raise_for_status = unittest.mock.MagicMock()

    with (
        unittest.mock.patch("requests.post", return_value=mock_post_res),
        unittest.mock.patch("requests.get", return_value=mock_get_res),
    ):
        db.download_db(local_engine)

    # 3. sql_content が空の場合
    mock_post_empty = unittest.mock.MagicMock()
    mock_post_empty.json.return_value = {
        "success": True,
        "result": {
            "sql": "",
        },
    }
    with unittest.mock.patch("requests.post", return_value=mock_post_empty):
        with pytest.raises(RuntimeError, match="D1 export returned empty SQL content"):
            db.download_db(local_engine)

    # 4. データベース復旧（restore）中に例外が発生した場合
    mock_post_success = unittest.mock.MagicMock()
    mock_post_success.json.return_value = {
        "success": True,
        "result": {
            "sql": "INVALID SQL STATEMENT;",
        },
    }
    with unittest.mock.patch("requests.post", return_value=mock_post_success):
        with pytest.raises(Exception):
            db.download_db(local_engine)


def test_send_batch_failure() -> None:
    # _send_batch で success が False の場合のエラー分岐をカバー
    mock_client = unittest.mock.MagicMock()
    mock_response = unittest.mock.MagicMock()
    mock_response.json.return_value = {
        "success": False,
        "errors": [{"message": "Mock D1 Query Error"}],
    }
    mock_response.raise_for_status = unittest.mock.MagicMock()
    mock_client.post.return_value = mock_response

    # httpx.Client コンテキストマネージャのモック
    with unittest.mock.patch(
        "httpx.Client",
        return_value=unittest.mock.MagicMock(
            __enter__=unittest.mock.MagicMock(return_value=mock_client)
        ),
    ):
        db._send_batch(
            [{"sql": "INSERT INTO dummy VALUES (1);"}],
            [("dummy", 1, "INSERT INTO dummy VALUES (1);")],
        )


def test_after_cursor_execute_exception_coverage() -> None:
    # statement 解析中に例外が発生した場合のログ出力をカバー
    # cursor として None を渡し、かつ statement に INSERT を含むことで、
    # cursor.lastrowid アクセス時に AttributeError を発生させる
    db.after_cursor_execute(
        conn=None,
        cursor=None,
        statement="INSERT INTO dummy VALUES (1);",
        parameters=[],
        context=None,
        executemany=False,
    )
