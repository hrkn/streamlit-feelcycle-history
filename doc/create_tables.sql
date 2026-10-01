-- SQLite3 DDL
-- Feelcycle受講履歴管理システム用テーブル構築スクリプト

-- 外部キー制約を一時的に無効化して安全にテーブルを削除
PRAGMA foreign_keys = OFF;

-- テーブル削除
DROP TABLE IF EXISTS web_account_history_updates;
DROP TABLE IF EXISTS lesson_histories;
DROP TABLE IF EXISTS lessons;
DROP TABLE IF EXISTS programs;
DROP TABLE IF EXISTS web_accounts;
DROP TABLE IF EXISTS members;

PRAGMA foreign_keys = ON;

-- 1. members テーブルの作成
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(20) NOT NULL
);

-- 2. web_accounts テーブルの作成
CREATE TABLE IF NOT EXISTS web_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email VARCHAR(50) NOT NULL UNIQUE,
    member_id INTEGER NOT NULL,
    icon VARCHAR(8) NOT NULL,
    FOREIGN KEY (member_id) REFERENCES members (id)
);

-- 3. programs テーブルの作成
CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(12) NOT NULL UNIQUE,
    background_color VARCHAR(20),
    text_color VARCHAR(20)
);

-- 4. lessons テーブルの作成
CREATE TABLE IF NOT EXISTS lessons (
    sid VARCHAR(160) PRIMARY KEY,
    store_id INTEGER NOT NULL,
    store_name VARCHAR(20) NOT NULL,
    instructor_id_1 INTEGER NOT NULL,
    instructor_name_1 VARCHAR(20) NOT NULL,
    instructor_id_2 INTEGER,
    instructor_name_2 VARCHAR(20),
    start_at DATETIME NOT NULL,
    end_at DATETIME NOT NULL,
    program_id INTEGER NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (program_id) REFERENCES programs (id)
);

-- 5. lesson_histories テーブルの作成
CREATE TABLE IF NOT EXISTS lesson_histories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    web_account_id INTEGER NOT NULL,
    lesson_sid VARCHAR(160) NOT NULL,
    bike_number VARCHAR(20) NOT NULL,
    ticket_type VARCHAR(100),
    is_absent BOOLEAN NOT NULL DEFAULT 0,
    FOREIGN KEY (web_account_id) REFERENCES web_accounts (id),
    FOREIGN KEY (lesson_sid) REFERENCES lessons (sid)
);

-- 6. web_account_history_updates テーブルの作成
CREATE TABLE IF NOT EXISTS web_account_history_updates (
    web_account_id INTEGER NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    last_updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (web_account_id, year, month),
    FOREIGN KEY (web_account_id) REFERENCES web_accounts (id)
);

-- 7. インデックスの作成
CREATE INDEX IF NOT EXISTS idx_web_accounts_email ON web_accounts (email);
CREATE INDEX IF NOT EXISTS idx_web_accounts_member_id ON web_accounts (member_id);
CREATE INDEX IF NOT EXISTS idx_programs_name ON programs (name);
CREATE INDEX IF NOT EXISTS idx_lessons_store_id ON lessons (store_id);
CREATE INDEX IF NOT EXISTS idx_lessons_start_at ON lessons (start_at);
CREATE INDEX IF NOT EXISTS idx_lessons_program_id ON lessons (program_id);
CREATE INDEX IF NOT EXISTS idx_lesson_histories_web_account_id ON lesson_histories (web_account_id);
CREATE INDEX IF NOT EXISTS idx_lesson_histories_lesson_sid ON lesson_histories (lesson_sid);
CREATE INDEX IF NOT EXISTS idx_web_account_history_updates_web_account_id ON web_account_history_updates (web_account_id);
