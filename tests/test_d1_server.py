import os

import requests

PORT = 8787
BASE_URL = f"http://127.0.0.1:{PORT}"
ACCOUNT_ID = "test-account-id"
DATABASE_ID = "test-database-id"
VALID_TOKEN = "test-api-token"


def test_d1_server_query_without_auth() -> None:
    # 認証ヘッダーなしでクエリ実行を試みた場合、401 Unauthorized で遮断されること
    url = f"{BASE_URL}/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"
    payload = {"sql": "SELECT 1;"}
    res = requests.post(url, json=payload, timeout=15.0)

    assert res.status_code == 401
    data = res.json()
    assert data.get("success") is False
    assert any(
        "Authentication error" in err.get("message", "")
        for err in data.get("errors", [])
    )


def test_d1_server_query_with_invalid_auth() -> None:
    # 不正な Bearer トークンでクエリ実行を試みた場合、401 Unauthorized で遮断されること
    url = f"{BASE_URL}/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"
    payload = {"sql": "SELECT 1;"}
    headers = {"Authorization": "Bearer invalid-wrong-token"}
    res = requests.post(url, headers=headers, json=payload, timeout=15.0)

    assert res.status_code == 401
    data = res.json()
    assert data.get("success") is False
    assert any(
        "Authentication error" in err.get("message", "")
        for err in data.get("errors", [])
    )


def test_d1_server_query_with_valid_auth() -> None:
    # 正しい Bearer トークンでクエリ実行した場合は正常に 200 が返ること
    url = f"{BASE_URL}/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"
    payload = {"sql": "SELECT 1 as num;"}
    headers = {"Authorization": f"Bearer {VALID_TOKEN}"}
    res = requests.post(url, headers=headers, json=payload, timeout=15.0)

    assert res.status_code == 200
    data = res.json()
    assert data.get("success") is True


def test_d1_server_export_without_auth() -> None:
    # 認証ヘッダーなしでエクスポートを試みた場合、401 Unauthorized で遮断されること
    url = f"{BASE_URL}/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/export"
    res = requests.post(url, json={"output_format": "file"}, timeout=15.0)

    assert res.status_code == 401
    data = res.json()
    assert data.get("success") is False
    assert any(
        "Authentication error" in err.get("message", "")
        for err in data.get("errors", [])
    )


def test_d1_server_export_with_valid_auth() -> None:
    # 正しい Bearer トークンでエクスポートした場合は正常に 200 が返ること
    url = f"{BASE_URL}/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/export"
    headers = {"Authorization": f"Bearer {VALID_TOKEN}"}
    res = requests.post(
        url, headers=headers, json={"output_format": "file"}, timeout=15.0
    )

    assert res.status_code == 200
    data = res.json()
    assert data.get("success") is True
    assert "sql" in data.get("result", {})
