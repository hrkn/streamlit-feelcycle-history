# Streamlit + Cloudflare D1 Feelcycle 履歴管理システム

Feelcycle 公式マイページからレッスン受講履歴を取得し、蓄積・管理・可視化するための Streamlit アプリケーションです。

## 概要
本プロジェクトは、SQLAlchemy および `sqlalchemy-cloudflare-d1` ダイアレクトを用いて Cloudflare D1 と通信する Streamlit アプリケーションです。
応答速度を向上させるため、ローカルの SQLite データベースへ書き込みを行い、バックグラウンドの同期スレッドが非同期で本番の Cloudflare D1 に反映（同期）する独自のアーキテクチャを採用しています。

また、ローカル開発およびテスト向けに、Cloudflare D1 HTTP API をエミュレートするローカル Mock サーバー (`d1-local-server`) を同梱しており、本番環境に接続することなくローカル環境完結で開発・テストが行えます。

## ディレクトリ構成
- `src/streamlit_feelcycle/`: Streamlit アプリケーションのメインパッケージ
  - [main.py](file:///c:/Users/mcs/Documents/develop/streamlit-feelcycle-history/src/streamlit_feelcycle/main.py): アプリケーションのエントリーポイントおよび UI 処理（ログイン、マイページ情報取得、履歴の可視化）
  - [database.py](file:///c:/Users/mcs/Documents/develop/streamlit-feelcycle-history/src/streamlit_feelcycle/database.py): データベース接続設定、SQLite-D1間の非同期同期処理
  - [model.py](file:///c:/Users/mcs/Documents/develop/streamlit-feelcycle-history/src/streamlit_feelcycle/model.py): SQLAlchemy を用いたデータベースモデル定義（Person, WebMember, Lesson, Program, LessonHistory など）
- `d1-local-server/`: Cloudflare D1 API をエミュレートするローカル Worker サーバー
- `doc/`: データベース設計書、テーブル定義 SQL ファイル
- `tests/`: pytest によるテストスイート

## 前提条件
本プロジェクトを動作させるには、以下のツールがインストールされている必要があります。
- Python 3.13以上
- [mise](https://mise.jdx.dev/) (Python バージョン管理)
- [uv](https://github.com/astral-sh/uv) (依存関係・パッケージ管理)
- Node.js / npm (Wrangler によるローカル Mock サーバー実行用)

## セットアップ手順

### 1. 依存関係のインストール
プロジェクトのルートディレクトリで以下を実行し、Python の仮想環境と依存関係をセットアップします。非公式 API クライアントである `feelpycle` も自動的に Git からインストールされます。
```bash
uv sync
```

### 2. 環境変数の設定
`.env.example` をコピーして `.env` ファイルを作成し、必要な環境変数を設定します。
```bash
cp .env.example .env
```
`.env` ファイル内に Cloudflare の認証情報およびデータベース情報を設定してください。
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_DATABASE_ID`

※ローカルの Mock サーバーを使用して動作させる場合は、`CF_D1_BASE_URL=http://localhost:8787` を指定します。

### 3. ローカル D1 データベースの初期化
ローカルで D1 Mock サーバーを実行するにあたり、SQLite データベースのスキーマ初期化とテストデータの投入を行います。
```bash
npx wrangler d1 execute my-first-db --local --file=doc/create_tables.sql
```

## 起動方法

### 1. ローカル Mock D1 サーバーの起動
ローカル環境で動作させる場合、別のターミナルで Wrangler を起動して Mock サーバーを立ち上げます。
```bash
npx wrangler dev --port 8787
```

### 2. Streamlit アプリケーションの起動
Streamlit アプリケーションを起動します。
```bash
uv run streamlit run src/streamlit_feelcycle/main.py
```
起動後、ブラウザで `http://localhost:8501` にアクセスしてください。

## テストの実行
単体テストの実行およびカバレッジの測定手順です。テスト実行時、Wrangler による Mock サーバーは自動で起動・終了されます。

### テスト実行
```bash
uv run pytest
```

### カバレッジの測定
```bash
uv run pytest --cov=src --cov-report=term-missing
```
※テスト方針の詳細は [tests/test_policy.md](file:///c:/Users/mcs/Documents/develop/streamlit-feelcycle-history/tests/test_policy.md) を参照してください。

## コード品質の管理
本プロジェクトでは ruff を使用してコードの静的解析とフォーマットを行っています。

### リンターの実行と修正
```bash
uv run ruff check --select I --fix
```

### フォーマッターの実行
```bash
uv run ruff format
```
