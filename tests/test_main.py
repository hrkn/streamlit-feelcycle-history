import datetime
import pathlib
import unittest.mock

import feelpycle.api
import pytest
import sqlalchemy
import sqlalchemy.orm
import streamlit.testing.v1

import streamlit_feelcycle.database as db
import streamlit_feelcycle.model as model

MAIN_PY_PATH = str(
    pathlib.Path(__file__).parent.parent / "src" / "streamlit_feelcycle" / "main.py"
)

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
    while not db.sync_queue.empty():
        try:
            db.sync_queue.get_nowait()
        except Exception:
            break

    d1_engine = get_d1_engine()
    local_engine = db.get_local_engine()

    # D1 (Mock Server) 側の初期化
    for tbl in reversed(model.Base.metadata.sorted_tables):
        try:
            with d1_engine.begin() as conn:
                conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS "{tbl.name}"'))
        except Exception:
            pass
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

    # ローカル (SQLite) 側の初期化
    model.Base.metadata.drop_all(local_engine)
    model.Base.metadata.create_all(local_engine)
    with sqlalchemy.orm.Session(local_engine) as session:
        # ローカルDBにはAliceのみ登録されている状態にする
        member = model.Member(name="Alice")
        session.add(member)
        session.flush()

        web_account = model.WebAccount(
            email="alice@example.com", member_id=member.id, icon=""
        )
        session.add(web_account)
        session.commit()


def test_login_and_registration() -> None:
    # 統合テスト: ログイン成功時のDB新規登録の挙動テスト
    at = streamlit.testing.v1.AppTest.from_file(MAIN_PY_PATH)

    # 未登録のEmail
    new_email = "new_user@example.com"

    # feelpycle.api.Account.login と mypage をモック
    mock_account_instance = unittest.mock.MagicMock()
    mock_account_instance.login.return_value = True

    mock_mypage = unittest.mock.MagicMock()
    mock_mypage.member_name = "Charlie"
    mock_mypage.store = ["RPG"]
    mock_mypage.member_type = "マンスリー30"
    mock_account_instance.mypage.return_value = mock_mypage
    mock_account_instance.get_first_lesson_date.return_value = datetime.datetime(
        2024, 1, 1, 10, 0
    )

    with unittest.mock.patch(
        "feelpycle.api.Account", return_value=mock_account_instance
    ):
        at.run(timeout=30)

        # フォームの値を入力してサブミット
        at.text_input[0].input(new_email)
        at.text_input[1].input("password123")
        at.button[0].click().run(timeout=30)

        # ログイン成功がセッションに反映されていることを確認
        assert at.session_state.logged_in
        assert at.session_state.email == new_email
        assert "ログイン中: Charlie" in at.sidebar.markdown[0].value
        assert "RPG / マンスリー30" in at.sidebar.caption[0].value

        # ローカルDBおよびD1側に新規レコードが登録されているか検証
        with sqlalchemy.orm.Session(db.get_local_engine()) as session:
            stmt = sqlalchemy.select(model.WebAccount).where(
                model.WebAccount.email == new_email
            )
            web_account = session.scalars(stmt).first()
            assert web_account is not None
            assert web_account.member.name == "Charlie"
            assert web_account.icon == "🚴"


def test_history_ui_and_sync() -> None:
    at = streamlit.testing.v1.AppTest.from_file(MAIN_PY_PATH)

    mock_account_instance = unittest.mock.MagicMock()
    mock_account_instance.login.return_value = True
    mock_account_instance.get_first_lesson_date.return_value = datetime.datetime(
        2024, 4, 1, 10, 0
    )

    mock_mypage = unittest.mock.MagicMock()
    mock_mypage.member_name = "Alice"
    mock_mypage.store = ["SJK"]
    mock_mypage.member_type = "マンスリー"
    mock_account_instance.mypage.return_value = mock_mypage

    instructor = feelpycle.api.Instructor(id=101, name="Anna")
    prog_search = feelpycle.api.ProgramSearch(id=1, name="BB2 MLN 2")
    inst_search = feelpycle.api.InstructorSearch(id="101", name="Anna")
    lesson1 = feelpycle.api.LessonInfo(
        sid="lesson_sid_001",
        shift_date="2026/09/01",
        ls_st=datetime.time(10, 0, 0),
        ls_et=datetime.time(10, 45, 0),
        store_name="新宿",
        iname="BB2 MLN 2",
        instructor_name_list=[instructor],
        sheet_no=12,
        ticket_name="マンスリー",
        program_search=prog_search,
        genre_search=[],
        instructor_search=inst_search,
        playlist_url="",
        cancel_flg=0,
        cancel_cancel_flg=0,
    )
    mock_month_history = feelpycle.api.MonthHistory(
        summary_count=10,
        member_count=1,
        ticket_count=0,
        lesson_info=[lesson1],
    )
    mock_account_instance.get_lesson_history.return_value = mock_month_history

    with unittest.mock.patch(
        "feelpycle.api.Account", return_value=mock_account_instance
    ):
        at.run(timeout=30)
        # Aliceでログイン (ログイン直後に自動で履歴が更新される)
        at.text_input[0].input("alice@example.com")
        at.text_input[1].input("password123")
        at.button[0].click().run(timeout=30)

        assert at.session_state.logged_in
        # 受講履歴ヘッダーが表示されていること
        assert any("受講履歴" in s.value for s in at.subheader)

        # 年月選択セレクトボックスの検証 (統合、降順、最新年月が先頭でデフォルト選択)
        ym_sb = next(s for s in at.selectbox if s.key == "history_selected_year_month")
        now = datetime.datetime.now()
        expected_yms = [
            f"{y}年{m}月"
            for y in range(now.year, 2024 - 1, -1)
            for m in range(12, 0, -1)
            if (y, m) <= (now.year, now.month) and (y, m) >= (2024, 4)
        ]
        assert ym_sb.options == expected_yms
        assert str(ym_sb.value) == f"{now.year}年{now.month}月"

        # Statisticsタブの集計期間セレクトボックスの検証
        stat_sb = next(s for s in at.selectbox if s.key == "statistics_selected_period")
        assert stat_sb.options[0] == "全期間"
        assert f"{now.year}年全体" in stat_sb.options
        assert f"{now.year}年{now.month}月" in stat_sb.options
        assert str(stat_sb.value) == "全期間"

        # 期間を年全体に切り替えて実行できることを検証
        stat_sb.select(f"{now.year}年全体").run(timeout=30)
        assert stat_sb.value == f"{now.year}年全体"

        # Total: xxx が大きめの文字サイズ (### Total: 1) で表示されていること
        assert any("Total: 1" in m.value for m in at.markdown)

        # ログイン時の自動更新によりサマリー指標 (metric) が表示されること
        metrics = [m.value for m in at.metric]
        assert len(metrics) > 0
        # データフレームが存在すること (当月分のデータが自動取得済み)
        assert len(at.dataframe) > 0


def test_duplicate_account_registration_blocked() -> None:
    at = streamlit.testing.v1.AppTest.from_file(MAIN_PY_PATH)

    mock_account_instance = unittest.mock.MagicMock()
    mock_account_instance.login.return_value = True
    mock_account_instance.get_first_lesson_date.return_value = datetime.datetime(
        2024, 1, 1, 10, 0
    )
    mock_mypage = unittest.mock.MagicMock()
    mock_mypage.member_name = "Alice"
    mock_mypage.store = ["RPG"]
    mock_mypage.member_type = "マンスリー"
    mock_account_instance.mypage.return_value = mock_mypage

    with unittest.mock.patch(
        "feelpycle.api.Account", return_value=mock_account_instance
    ):
        at.run(timeout=30)
        # Aliceでログイン
        at.text_input[0].input("alice@example.com")
        at.text_input[1].input("password123")
        at.button[0].click().run(timeout=30)

        assert at.session_state.logged_in

        # 「➕ アカウント追加」ボタンをクリックしてダイアログを開く
        add_btn = next(b for b in at.sidebar.button if "アカウント追加" in b.label)
        add_btn.click().run(timeout=30)

        # ダイアログ内のフォームに既存の alice@example.com を入力して送信
        at.text_input[0].input("alice@example.com")
        at.text_input[1].input("password123")

        # ダイアログを開いた状態を維持しながら送信ボタンをクリック
        new_add_btn = next(b for b in at.sidebar.button if "アカウント追加" in b.label)
        submit_btn = next(b for b in at.button if "追加して履歴を同期" in b.label)
        new_add_btn.click()
        submit_btn.click().run(timeout=30)

        # 「既に連携済みのアカウントです。」のエラーが表示されること
        assert any("既に連携済みのアカウントです。" in e.value for e in at.error)


def test_unlink_button_behavior() -> None:
    # ローカルDBにAliceの2つ目のWebアカウントを追加
    with sqlalchemy.orm.Session(db.get_local_engine()) as session:
        alice_member = session.scalars(
            sqlalchemy.select(model.Member).where(model.Member.name == "Alice")
        ).first()
        assert alice_member is not None
        wa_second = model.WebAccount(
            email="alice_sub@example.com",
            member_id=alice_member.id,
            icon="🐱",
        )
        session.add(wa_second)
        session.commit()
        second_wa_id = wa_second.id

    at = streamlit.testing.v1.AppTest.from_file(MAIN_PY_PATH)

    mock_account_instance = unittest.mock.MagicMock()
    mock_account_instance.login.return_value = True
    mock_account_instance.get_first_lesson_date.return_value = datetime.datetime(
        2024, 1, 1, 10, 0
    )
    mock_mypage = unittest.mock.MagicMock()
    mock_mypage.member_name = "Alice"
    mock_mypage.store = ["RPG"]
    mock_mypage.member_type = "マンスリー"
    mock_account_instance.mypage.return_value = mock_mypage

    with unittest.mock.patch(
        "feelpycle.api.Account", return_value=mock_account_instance
    ):
        at.run(timeout=30)
        # alice@example.com でログイン
        at.text_input[0].input("alice@example.com")
        at.text_input[1].input("password123")
        at.button[0].click().run(timeout=30)

        assert at.session_state.logged_in

        # サイドバー上の解除ボタンを検証
        unlink_btns = [
            b for b in at.sidebar.button if b.key and b.key.startswith("unlink_btn_")
        ]
        assert len(unlink_btns) == 2

        # ログイン中のアカウントのボタンは無効 (disabled=True)
        login_btn = next(
            b for b in unlink_btns if "ログイン中のため解除できません" in (b.help or "")
        )
        assert login_btn.disabled is True

        # 別アカウント (alice_sub@example.com) のボタンは有効 (disabled=False)
        sub_btn = next(b for b in unlink_btns if f"unlink_btn_{second_wa_id}" == b.key)
        assert sub_btn.disabled is False

        # 解除ボタンをクリックしてダイアログを開く
        sub_btn.click().run(timeout=30)

        # ダイアログを開いた状態を維持しながら「解除する」ボタンをクリック
        new_sub_btn = next(
            b for b in at.sidebar.button if f"unlink_btn_{second_wa_id}" == b.key
        )
        confirm_btn = next(
            b for b in at.button if b.key == f"confirm_unlink_{second_wa_id}"
        )
        new_sub_btn.click()
        confirm_btn.click().run(timeout=30)

        # 解除後、ローカルDBから alice_sub@example.com が削除されていること
        with sqlalchemy.orm.Session(db.get_local_engine()) as session:
            deleted_wa = session.get(model.WebAccount, second_wa_id)
            assert deleted_wa is None

        # 残った連携アカウントが1つだけの場合、解除ボタンが無効化されていること
        remaining_unlink_btns = [
            b for b in at.sidebar.button if b.key and b.key.startswith("unlink_btn_")
        ]
        assert len(remaining_unlink_btns) == 1
        assert remaining_unlink_btns[0].disabled is True
