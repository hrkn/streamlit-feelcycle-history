import json
import math
import re
from typing import Any
import urllib.parse

# pyrefly: ignore [missing-import]
from workers import Response, WorkerEntrypoint


SAFE_IDENTIFIER_REGEX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_identifier(name: str) -> str:
    """Validate and safely double-quote a SQLite identifier (table or column name)."""
    if not isinstance(name, str):
        raise ValueError(f"Identifier must be a string, got {type(name).__name__}")
    if "\x00" in name:
        raise ValueError("Identifier contains null bytes")
    if SAFE_IDENTIFIER_REGEX.match(name):
        return f'"{name}"'
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def format_sql_literal(v: Any) -> str:
    """Format a Python value into a safe SQLite literal."""
    if v is None:
        return "NULL"
    # In Python, isinstance(True, int) is True, so check bool first
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return "NULL"
        return repr(v)
    if isinstance(v, (bytes, bytearray)):
        return f"X'{bytes(v).hex()}'"
    if isinstance(v, str):
        sanitized = v.replace("\x00", "")
        escaped = sanitized.replace("'", "''")
        return f"'{escaped}'"
    sanitized_json = json.dumps(v, ensure_ascii=False).replace("\x00", "")
    escaped = sanitized_json.replace("'", "''")
    return f"'{escaped}'"


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        env = self.env
        url = request.url
        method = request.method
        print(f"url: {url}, method: {method}")

        # パスの抽出
        path = urllib.parse.urlparse(url).path

        # 末尾が /raw または /query である場合にマッチ
        is_query = path.endswith("/raw") or path.endswith("/query")
        is_export = path.endswith("/export")

        if not (is_query or is_export):
            return Response("Not Found", status=404)

        # 認証の検証 (Cloudflare D1 REST API 仕様準拠)
        auth_header = None
        if hasattr(request, "headers") and request.headers:
            auth_header = request.headers.get("Authorization") or request.headers.get(
                "authorization"
            )

        is_authenticated = False
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            expected_token = getattr(env, "API_TOKEN", None)
            if expected_token:
                is_authenticated = token == expected_token
            else:
                is_authenticated = bool(token)

        if not is_authenticated:
            error_response = {
                "result": None,
                "success": False,
                "errors": [
                    {
                        "code": 10000,
                        "message": "Authentication error",
                    }
                ],
                "messages": [],
            }
            print(f"Error (Unauthorized): {error_response}")
            return Response(
                json.dumps(error_response),
                headers={"Content-Type": "application/json"},
                status=401,
            )

        if method == "POST" and is_export:
            try:
                tables_res = await env.DB.prepare(
                    "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%'"
                ).all()
                tables_raw = (
                    tables_res.results.to_py()
                    if hasattr(tables_res.results, "to_py")
                    else tables_res.results
                )

                sql_dump = []
                for t in tables_raw:
                    table_name = t.get("name")
                    create_sql = t.get("sql")
                    if not table_name:
                        continue
                    if create_sql:
                        sql_dump.append(f"{create_sql};")

                    quoted_table = quote_identifier(table_name)
                    data_res = await env.DB.prepare(
                        f"SELECT * FROM {quoted_table}"
                    ).all()
                    rows_raw = (
                        data_res.results.to_py()
                        if hasattr(data_res.results, "to_py")
                        else data_res.results
                    )
                    for row in rows_raw:
                        quoted_cols = ", ".join(
                            [quote_identifier(k) for k in row.keys()]
                        )
                        vals_str = ", ".join(
                            [format_sql_literal(v) for v in row.values()]
                        )
                        sql_dump.append(
                            f"INSERT INTO {quoted_table} ({quoted_cols}) VALUES ({vals_str});"
                        )

                sql_content = "\n".join(sql_dump)

                mock_response = {
                    "result": {
                        "filename": "my-first-db.sql",
                        "sql": sql_content,
                    },
                    "success": True,
                    "errors": [],
                    "messages": [],
                }
                print(f"Response (Export): {mock_response}")
                return Response(
                    json.dumps(mock_response),
                    headers={"Content-Type": "application/json"},
                )
            except Exception as e:
                error_response = {
                    "result": None,
                    "success": False,
                    "errors": [
                        {
                            "code": 1000,
                            "message": f"D1 Local Mock Export Error: {str(e)}",
                        }
                    ],
                    "messages": [],
                }
                print(f"Error: {error_response}")
                return Response(
                    json.dumps(error_response),
                    headers={"Content-Type": "application/json"},
                    status=500,
                )

        if method == "POST" and is_query:
            account_id = "local"
            database_id = "local"
            match = re.search(r"/accounts/([^/]+)/d1/database/([^/]+)", path)
            if match:
                account_id, database_id = match.groups()

            try:
                body = await request.json()
                body_py = body.to_py() if hasattr(body, "to_py") else body

                if isinstance(body_py, list):
                    error_response = {
                        "result": None,
                        "success": False,
                        "errors": [
                            {
                                "code": 1000,
                                "message": "D1 REST API does not support batch arrays in the request body. Send a single query object instead.",
                            }
                        ],
                        "messages": [],
                    }
                    print(f"Error (Array rejected): {error_response}")
                    return Response(
                        json.dumps(error_response),
                        headers={"Content-Type": "application/json"},
                        status=400,
                    )

                queries = [body_py]

                query_results = []
                for q in queries:
                    sql = q.get("sql")
                    params = q.get("params", [])

                    # クエリの実行
                    statement = env.DB.prepare(sql).bind(*params)
                    db_res = await statement.all()

                    # D1 Pythonバインディングのメタデータから変更行数を取得
                    db_meta = (
                        db_res.meta.to_py()
                        if hasattr(db_res.meta, "to_py")
                        else db_res.meta
                    )
                    changes = db_meta.get("changes", 0) if db_meta else 0
                    duration = db_meta.get("duration", 0) if db_meta else 0
                    last_row_id = db_meta.get("last_row_id") if db_meta else None

                    # results を raw 形式に変換
                    results_raw = db_res.results.to_py() if db_res.results else []
                    columns = []
                    rows = []
                    if results_raw:
                        first = results_raw[0]
                        if isinstance(first, dict):
                            columns = list(first.keys())
                            for row in results_raw:
                                rows.append([row.get(col) for col in columns])
                    else:
                        # 結果が空で SELECT クエリの場合、カラム名を取得するために raw() を試みる
                        if sql.strip().upper().startswith("SELECT"):
                            try:
                                stmt2 = env.DB.prepare(sql).bind(*params)
                                raw_res = await stmt2.raw({"columnNames": True})
                                raw_res_py = (
                                    raw_res.to_py()
                                    if hasattr(raw_res, "to_py")
                                    else raw_res
                                )
                                if raw_res_py and len(raw_res_py) > 0:
                                    columns = list(raw_res_py[0])
                            except Exception as e:
                                print(f"Failed to get column names: {e}")

                    query_results.append(
                        {
                            "success": True,
                            "meta": {
                                "served_by": "local-worker-d1-api",
                                "account_id": account_id,
                                "database_id": database_id,
                                "changes": changes,
                                "duration": duration,
                                "last_row_id": last_row_id,
                            },
                            "results": {
                                "columns": columns,
                                "rows": rows,
                            },
                        }
                    )

                mock_response = {
                    "result": query_results,
                    "success": True,
                    "errors": [],
                    "messages": [],
                }
                print(f"Response: {mock_response}")
                return Response(
                    json.dumps(mock_response),
                    headers={"Content-Type": "application/json"},
                )

            except Exception as e:
                error_response = {
                    "result": None,
                    "success": False,
                    "errors": [
                        {"code": 1000, "message": f"D1 Local Mock Error: {str(e)}"}
                    ],
                    "messages": [],
                }
                print(f"Error: {error_response}")
                return Response(
                    json.dumps(error_response),
                    headers={"Content-Type": "application/json"},
                    status=500,
                )

        return Response("Not Found", status=404)
