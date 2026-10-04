import datetime
import unittest.mock

import feelpycle.api
import pytest
import sqlalchemy
import sqlalchemy.orm

import streamlit_feelcycle.history as history
import streamlit_feelcycle.model as model
import streamlit_feelcycle.wrapper as wrapper


@pytest.fixture
def session() -> sqlalchemy.orm.Session:
    engine = sqlalchemy.create_engine("sqlite:///:memory:")
    model.Base.metadata.create_all(engine)
    Session = sqlalchemy.orm.sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


def create_dummy_month_history() -> feelpycle.api.MonthHistory:
    instructor = feelpycle.api.Instructor(id=101, name="Anna")
    instructor_sub = feelpycle.api.Instructor(id=102, name="Bob")
    prog_search = feelpycle.api.ProgramSearch(id=1, name="BB2 MLN 2")
    inst_search = feelpycle.api.InstructorSearch(id="101", name="Anna")

    lesson1 = feelpycle.api.LessonInfo(
        sid="lesson_sid_001",
        shift_date="2026/09/01",
        ls_st=datetime.time(10, 0, 0),
        ls_et=datetime.time(10, 45, 0),
        store_name="新宿",
        iname="BB2 MLN 2",
        instructor_name_list=[instructor, instructor_sub],
        sheet_no=12,
        ticket_name="マンスリー30",
        program_search=prog_search,
        genre_search=[],
        instructor_search=inst_search,
        playlist_url="",
        cancel_flg=0,
        cancel_cancel_flg=0,
    )

    lesson2 = feelpycle.api.LessonInfo(
        sid="lesson_sid_002",
        shift_date="2026/09/15",
        ls_st=datetime.time(19, 0, 0),
        ls_et=datetime.time(19, 45, 0),
        store_name="六本木",
        iname="BSW Hit 8",
        instructor_name_list=[instructor],
        sheet_no=5,
        ticket_name="1回券",
        program_search=prog_search,
        genre_search=[],
        instructor_search=inst_search,
        playlist_url="",
        cancel_flg=1,  # キャンセル/欠席
        cancel_cancel_flg=0,
    )

    return feelpycle.api.MonthHistory(
        summary_count=50,
        member_count=1,
        ticket_count=0,
        lesson_info=[lesson1, lesson2],
    )


def test_fetch_and_save_monthly_history(session: sqlalchemy.orm.Session) -> None:
    # ユーザー準備
    member = model.Member(name="Test User")
    session.add(member)
    session.flush()
    web_account = model.WebAccount(
        email="test@example.com", member_id=member.id, icon=""
    )
    session.add(web_account)
    session.commit()

    # モックAccount
    mock_account = unittest.mock.MagicMock()
    mock_account.get_lesson_history.return_value = create_dummy_month_history()

    # 初回同期
    result = history.fetch_and_save_monthly_history(
        mock_account, web_account.id, 2026, 9, session
    )
    assert result is not None
    assert result.summary_count == 50

    # DBの確認
    programs = session.scalars(sqlalchemy.select(model.Program)).all()
    assert len(programs) == 2  # BB2 MLN 2 と BSW Hit 8

    lessons = session.scalars(sqlalchemy.select(model.Lesson)).all()
    assert len(lessons) == 2

    histories = session.scalars(sqlalchemy.select(model.LessonHistory)).all()
    assert len(histories) == 2

    # 1件目の確認
    h1 = session.scalars(
        sqlalchemy.select(model.LessonHistory).where(
            model.LessonHistory.lesson_sid == "lesson_sid_001"
        )
    ).first()
    assert h1 is not None
    assert h1.bike_number == "12"
    assert h1.ticket_type == "マンスリー30"
    assert h1.is_absent is False
    assert h1.lesson.instructor_name_2 == "Bob"

    # 2件目の確認 (欠席)
    h2 = session.scalars(
        sqlalchemy.select(model.LessonHistory).where(
            model.LessonHistory.lesson_sid == "lesson_sid_002"
        )
    ).first()
    assert h2 is not None
    assert h2.bike_number == "5"
    assert h2.is_absent is True
    assert h2.lesson.instructor_name_2 is None

    # 2回目の同期 (upsert動作検証: レコードが増えないこと)
    result_update = history.fetch_and_save_monthly_history(
        mock_account, web_account.id, 2026, 9, session
    )
    assert result_update is not None
    histories_after = session.scalars(sqlalchemy.select(model.LessonHistory)).all()
    assert len(histories_after) == 2


def test_fetch_and_save_error_cases(session: sqlalchemy.orm.Session) -> None:
    mock_account = unittest.mock.MagicMock()

    # 例外発生時
    mock_account.get_lesson_history.side_effect = RuntimeError("API Network Error")
    res1 = history.fetch_and_save_monthly_history(mock_account, 1, 2026, 9, session)
    assert res1 is None

    # None が返ってきた場合
    mock_account.get_lesson_history.side_effect = None
    mock_account.get_lesson_history.return_value = None
    res2 = history.fetch_and_save_monthly_history(mock_account, 1, 2026, 9, session)
    assert res2 is None


def test_get_monthly_histories_from_db(session: sqlalchemy.orm.Session) -> None:
    # ユーザー準備
    member = model.Member(name="User2")
    session.add(member)
    session.flush()
    web_account = model.WebAccount(
        email="user2@example.com", member_id=member.id, icon=""
    )
    session.add(web_account)
    session.flush()

    # 9月のレッスン
    prog = model.Program(name="BB1 Comp", background_color="#000", text_color="#fff")
    session.add(prog)
    session.flush()

    lesson_sep = model.Lesson(
        sid="sid_sep",
        store_id=1,
        store_name="銀座",
        instructor_id_1=10,
        instructor_name_1="Taro",
        start_at=datetime.datetime(2026, 9, 10, 12, 0),
        end_at=datetime.datetime(2026, 9, 10, 12, 45),
        program_id=prog.id,
    )
    lesson_oct = model.Lesson(
        sid="sid_oct",
        store_id=1,
        store_name="銀座",
        instructor_id_1=10,
        instructor_name_1="Taro",
        start_at=datetime.datetime(2026, 10, 5, 12, 0),
        end_at=datetime.datetime(2026, 10, 5, 12, 45),
        program_id=prog.id,
    )
    lesson_sep2 = model.Lesson(
        sid="sid_sep2",
        store_id=1,
        store_name="銀座",
        instructor_id_1=10,
        instructor_name_1="Taro",
        start_at=datetime.datetime(2026, 9, 5, 10, 0),
        end_at=datetime.datetime(2026, 9, 5, 10, 45),
        program_id=prog.id,
    )
    session.add_all([lesson_sep, lesson_sep2, lesson_oct])
    session.flush()

    h_sep = model.LessonHistory(
        web_account_id=web_account.id,
        lesson_sid=lesson_sep.sid,
        bike_number="1",
        ticket_type="マンスリー",
        is_absent=False,
    )
    h_sep2 = model.LessonHistory(
        web_account_id=web_account.id,
        lesson_sid=lesson_sep2.sid,
        bike_number="3",
        ticket_type="マンスリー",
        is_absent=False,
    )
    h_oct = model.LessonHistory(
        web_account_id=web_account.id,
        lesson_sid=lesson_oct.sid,
        bike_number="2",
        ticket_type="マンスリー",
        is_absent=False,
    )
    session.add_all([h_sep, h_sep2, h_oct])
    session.commit()

    # 9月分の取得 (受講日時の昇順で返されることの検証)
    list_sep = history.get_monthly_histories_from_db(web_account.id, 2026, 9, session)
    assert len(list_sep) == 2
    assert list_sep[0]["受講日"] == "2026/09/05"
    assert list_sep[0]["開始時刻"] == "10:00"
    assert list_sep[0]["_background_color"] == "#000"
    assert list_sep[0]["_text_color"] == "#fff"
    assert list_sep[1]["受講日"] == "2026/09/10"
    assert list_sep[1]["開始時刻"] == "12:00"
    assert list_sep[1]["_background_color"] == "#000"
    assert list_sep[1]["_text_color"] == "#fff"

    # 12月 (年末境界テスト)
    list_dec = history.get_monthly_histories_from_db(web_account.id, 2026, 12, session)
    assert len(list_dec) == 0


def test_style_monthly_histories() -> None:
    data = [
        {
            "受講日": "2026/09/01",
            "プログラム": "BB1 Comp",
            "_background_color": "#112233",
            "_text_color": "#445566",
        }
    ]
    styler = history.style_monthly_histories(data)
    assert styler is not None
    # 描画対象の列に _background_color, _text_color が含まれないこと
    assert "_background_color" not in styler.data.columns
    assert "_text_color" not in styler.data.columns
    assert "プログラム" in styler.data.columns
    html = styler.to_html()
    assert "background-color: #112233" in html
    assert "color: #445566" in html

    # 空データ
    styler_empty = history.style_monthly_histories([])
    assert styler_empty is not None


def test_get_monthly_summary(session: sqlalchemy.orm.Session) -> None:
    # ユーザー準備
    member = model.Member(name="User3")
    session.add(member)
    session.flush()
    web_account = model.WebAccount(
        email="user3@example.com", member_id=member.id, icon=""
    )
    session.add(web_account)
    session.flush()

    # API MonthHistory がある場合
    mock_mh = create_dummy_month_history()
    summary1 = history.get_monthly_summary(
        web_account.id, 2026, 9, session, month_history=mock_mh
    )
    assert summary1["total_count"] == 50
    assert summary1["monthly_count"] == 1
    assert summary1["member_count"] == 1
    assert summary1["ticket_count"] == 0

    # API MonthHistory が None で DB から集計する場合
    prog = model.Program(name="BSB", background_color="#000", text_color="#fff")
    session.add(prog)
    session.flush()

    lesson1 = model.Lesson(
        sid="s1",
        store_id=1,
        store_name="新宿",
        instructor_id_1=1,
        instructor_name_1="I1",
        start_at=datetime.datetime(2026, 9, 2, 10, 0),
        end_at=datetime.datetime(2026, 9, 2, 10, 45),
        program_id=prog.id,
    )
    lesson2 = model.Lesson(
        sid="s2",
        store_id=1,
        store_name="新宿",
        instructor_id_1=1,
        instructor_name_1="I1",
        start_at=datetime.datetime(2026, 9, 5, 10, 0),
        end_at=datetime.datetime(2026, 9, 5, 10, 45),
        program_id=prog.id,
    )
    session.add_all([lesson1, lesson2])
    session.flush()

    h1 = model.LessonHistory(
        web_account_id=web_account.id,
        lesson_sid=lesson1.sid,
        bike_number="1",
        ticket_type="マンスリー",
        is_absent=False,
    )
    h2 = model.LessonHistory(
        web_account_id=web_account.id,
        lesson_sid=lesson2.sid,
        bike_number="2",
        ticket_type="他店舗利用券",
        is_absent=False,
    )
    session.add_all([h1, h2])
    session.commit()

    summary2 = history.get_monthly_summary(
        web_account.id, 2026, 9, session, month_history=None
    )
    assert summary2["total_count"] == 2
    assert summary2["monthly_count"] == 2
    assert summary2["member_count"] == 1
    assert summary2["ticket_count"] == 1


def test_get_first_lesson_year_month(session: sqlalchemy.orm.Session) -> None:
    now = datetime.datetime.now()

    member = model.Member(name="UserFirstYM")
    session.add(member)
    session.flush()
    web_account = model.WebAccount(
        email="firstym@example.com", member_id=member.id, icon=""
    )
    session.add(web_account)
    session.flush()

    # 1. APIもDBも受講履歴がない場合 -> 現在年月
    res_default = history.get_first_lesson_year_month(None, web_account.id, session)
    assert res_default == (now.year, now.month)

    # 2. APIから初回受講日を取得できる場合
    mock_account = unittest.mock.MagicMock()
    mock_account.get_first_lesson_date.return_value = datetime.datetime(
        2021, 5, 20, 10, 0
    )
    res_api = history.get_first_lesson_year_month(mock_account, web_account.id, session)
    assert res_api == (2021, 5)

    # 3. APIが例外、DBにのみ受講履歴がある場合
    mock_account.get_first_lesson_date.side_effect = RuntimeError("API error")
    prog = model.Program(name="BB2 YM Test", background_color="#000", text_color="#fff")
    session.add(prog)
    session.flush()

    lesson_db = model.Lesson(
        sid="sid_first_ym_db",
        store_id=1,
        store_name="銀座",
        instructor_id_1=10,
        instructor_name_1="Taro",
        start_at=datetime.datetime(2023, 8, 15, 14, 0),
        end_at=datetime.datetime(2023, 8, 15, 14, 45),
        program_id=prog.id,
    )
    session.add(lesson_db)
    session.flush()

    h_db = model.LessonHistory(
        web_account_id=web_account.id,
        lesson_sid=lesson_db.sid,
        bike_number="10",
        ticket_type="マンスリー",
        is_absent=False,
    )
    session.add(h_db)
    session.commit()

    res_db = history.get_first_lesson_year_month(mock_account, web_account.id, session)
    assert res_db == (2023, 8)

    # 4. API (2020年3月) と DB (2023年8月) の両方がある場合 -> 最小年月 (2020年3月)
    mock_account.get_first_lesson_date.side_effect = None
    mock_account.get_first_lesson_date.return_value = datetime.datetime(
        2020, 3, 1, 9, 0
    )
    res_min = history.get_first_lesson_year_month(mock_account, web_account.id, session)
    assert res_min == (2020, 3)


# --- should_update_month テスト ---


def test_should_update_month_no_record(
    session: sqlalchemy.orm.Session,
) -> None:
    """更新履歴レコードが存在しない場合は True を返すこと。"""
    member = model.Member(name="SUM NoRec")
    session.add(member)
    session.flush()
    wa = model.WebAccount(email="sum_norec@example.com", member_id=member.id, icon="")
    session.add(wa)
    session.commit()

    now = datetime.datetime(2026, 9, 21, 12, 0, 0)
    assert history.should_update_month(wa.id, 2026, 8, now, session) is True


def test_should_update_month_not_next_month_or_later(
    session: sqlalchemy.orm.Session,
) -> None:
    """更新月が対象月の次の月以降ではない場合は True を返すこと。"""
    member = model.Member(name="SUM NotNextMonth")
    session.add(member)
    session.flush()
    wa = model.WebAccount(
        email="sum_not_next@example.com", member_id=member.id, icon=""
    )
    session.add(wa)
    session.commit()

    now = datetime.datetime(2026, 9, 21, 12, 0, 0)

    # ケース1: 当月(9月)を9月中(9/10)に更新済み -> 次の月(10月)以降ではない -> True
    r1 = model.WebAccountHistoryUpdate(
        web_account_id=wa.id,
        year=2026,
        month=9,
        last_updated_time=datetime.datetime(2026, 9, 10, 10, 0, 0),
    )
    session.add(r1)

    # ケース2: 過去月(8月)を8月中(8/20)に更新済み -> 次の月(9月)以降ではない -> True
    r2 = model.WebAccountHistoryUpdate(
        web_account_id=wa.id,
        year=2026,
        month=8,
        last_updated_time=datetime.datetime(2026, 8, 20, 10, 0, 0),
    )
    session.add(r2)

    # ケース3: 12月分を12月中(12/25)に更新済み -> 次の月(翌年1月)以降ではない -> True
    r3 = model.WebAccountHistoryUpdate(
        web_account_id=wa.id,
        year=2025,
        month=12,
        last_updated_time=datetime.datetime(2025, 12, 25, 10, 0, 0),
    )
    session.add(r3)
    session.commit()

    assert history.should_update_month(wa.id, 2026, 9, now, session) is True
    assert history.should_update_month(wa.id, 2026, 8, now, session) is True
    assert history.should_update_month(wa.id, 2025, 12, now, session) is True


def test_should_update_month_next_month_fresh(
    session: sqlalchemy.orm.Session,
) -> None:
    """対象月の次の月以降に更新済みで、かつ4か月未満の場合は False を返すこと。"""
    member = model.Member(name="SUM NextMonthFresh")
    session.add(member)
    session.flush()
    wa = model.WebAccount(email="sum_fresh@example.com", member_id=member.id, icon="")
    session.add(wa)
    session.commit()

    now = datetime.datetime(2026, 9, 21, 12, 0, 0)

    # ケース1: 8月分を9月(翌月)に更新済み、現在9/21(4か月未満) -> False
    r1 = model.WebAccountHistoryUpdate(
        web_account_id=wa.id,
        year=2026,
        month=8,
        last_updated_time=datetime.datetime(2026, 9, 1, 10, 0, 0),
    )
    session.add(r1)

    # ケース2: 2025年12月分を2026年1月(翌月)に更新済み、判定時2026年2月(4か月未満) -> False
    now_feb = datetime.datetime(2026, 2, 1, 12, 0, 0)
    r2 = model.WebAccountHistoryUpdate(
        web_account_id=wa.id,
        year=2025,
        month=12,
        last_updated_time=datetime.datetime(2026, 1, 5, 10, 0, 0),
    )
    session.add(r2)
    session.commit()

    assert history.should_update_month(wa.id, 2026, 8, now, session) is False
    assert history.should_update_month(wa.id, 2025, 12, now_feb, session) is False


def test_should_update_month_stale_data(
    session: sqlalchemy.orm.Session,
) -> None:
    """次の月以降に更新済みでも、4か月以上経過している場合は True を返すこと。"""
    member = model.Member(name="SUM Stale")
    session.add(member)
    session.flush()
    wa = model.WebAccount(email="sum_stale@example.com", member_id=member.id, icon="")
    session.add(wa)
    session.commit()

    now = datetime.datetime(2026, 9, 21, 12, 0, 0)
    # 2026年3月分を翌月4月5日に更新済み -> 最終更新から5か月経過 (4か月以上) -> True
    update_record = model.WebAccountHistoryUpdate(
        web_account_id=wa.id,
        year=2026,
        month=3,
        last_updated_time=datetime.datetime(2026, 4, 5, 10, 0, 0),
    )
    session.add(update_record)
    session.commit()

    assert history.should_update_month(wa.id, 2026, 3, now, session) is True


# --- upsert_history_update テスト ---


def test_upsert_history_update(session: sqlalchemy.orm.Session) -> None:
    """insert と update の両方の動作を検証する。"""
    member = model.Member(name="Upsert User")
    session.add(member)
    session.flush()
    wa = model.WebAccount(email="upsert@example.com", member_id=member.id, icon="")
    session.add(wa)
    session.commit()

    now1 = datetime.datetime(2026, 9, 1, 10, 0, 0)
    # insert
    history.upsert_history_update(wa.id, 2026, 9, now1, session)
    session.commit()

    stmt = sqlalchemy.select(model.WebAccountHistoryUpdate).where(
        model.WebAccountHistoryUpdate.web_account_id == wa.id,
        model.WebAccountHistoryUpdate.year == 2026,
        model.WebAccountHistoryUpdate.month == 9,
    )
    record = session.scalars(stmt).first()
    assert record is not None
    assert record.last_updated_time == now1

    # update
    now2 = datetime.datetime(2026, 9, 21, 15, 0, 0)
    history.upsert_history_update(wa.id, 2026, 9, now2, session)
    session.commit()

    session.expire_all()
    record_updated = session.scalars(stmt).first()
    assert record_updated is not None
    assert record_updated.last_updated_time == now2


# --- sync_all_histories テスト ---


def test_sync_all_histories(session: sqlalchemy.orm.Session) -> None:
    """一括更新の統合テスト。"""
    member = model.Member(name="Sync User")
    session.add(member)
    session.flush()
    wa = model.WebAccount(email="sync@example.com", member_id=member.id, icon="")
    session.add(wa)
    session.commit()

    mock_account = unittest.mock.MagicMock()
    # get_first_lesson_date: 2026年1月が初回
    mock_account.get_first_lesson_date.return_value = datetime.datetime(
        2026, 1, 1, 10, 0
    )
    # get_lesson_history: 常にダミーデータを返す
    mock_account.get_lesson_history.return_value = create_dummy_month_history()

    # now を 2026年9月とする
    fixed_now = datetime.datetime(2026, 9, 21, 12, 0, 0)
    with unittest.mock.patch("streamlit_feelcycle.history.datetime") as mock_datetime:
        mock_datetime.datetime.now.return_value = fixed_now
        mock_datetime.datetime.combine = datetime.datetime.combine
        mock_datetime.datetime.side_effect = lambda *args, **kw: datetime.datetime(
            *args, **kw
        )

        result = history.sync_all_histories(mock_account, wa.id, session)

    # 2026年1月~9月の9か月分が更新対象 (全て初回)
    assert result["updated"] == 9
    assert result["skipped"] == 0

    # web_account_history_updates に9件レコードがあること
    update_records = session.scalars(
        sqlalchemy.select(model.WebAccountHistoryUpdate).where(
            model.WebAccountHistoryUpdate.web_account_id == wa.id
        )
    ).all()
    assert len(update_records) == 9

    # get_lesson_history が9回呼ばれたこと
    assert mock_account.get_lesson_history.call_count == 9


def test_sync_all_histories_no_lesson_history(session: sqlalchemy.orm.Session) -> None:
    """初回受講年月(2026年8月)から現在(2026年9月)までの月が更新されること。"""
    member = model.Member(name="Sync NoLesson User")
    session.add(member)
    session.flush()
    wa = model.WebAccount(
        email="sync_nolesson@example.com", member_id=member.id, icon=""
    )
    session.add(wa)
    session.commit()

    mock_account = unittest.mock.MagicMock()
    # 初回受講年月: 2026年8月
    mock_account.get_first_lesson_date.return_value = datetime.datetime(
        2026, 8, 1, 10, 0
    )
    # 受講履歴なし (None) を返す
    mock_account.get_lesson_history.return_value = None

    fixed_now = datetime.datetime(2026, 9, 21, 12, 0, 0)
    with unittest.mock.patch("streamlit_feelcycle.history.datetime") as mock_datetime:
        mock_datetime.datetime.now.return_value = fixed_now
        mock_datetime.datetime.combine = datetime.datetime.combine
        mock_datetime.datetime.side_effect = lambda *args, **kw: datetime.datetime(
            *args, **kw
        )

        result = history.sync_all_histories(mock_account, wa.id, session)

    # 2026年8月~9月の2か月分すべて更新完了とカウントされること
    assert result["updated"] == 2
    assert result["skipped"] == 0

    # web_account_history_updates に2件レコードが作成されていること
    records = session.scalars(
        sqlalchemy.select(model.WebAccountHistoryUpdate).where(
            model.WebAccountHistoryUpdate.web_account_id == wa.id
        )
    ).all()
    assert len(records) == 2


def test_sync_all_histories_with_on_progress(session: sqlalchemy.orm.Session) -> None:
    """初回受講年月(2026年7月)からon_progressコールバックが正しく呼び出されること。"""
    member = model.Member(name="Sync Progress User")
    session.add(member)
    session.flush()
    wa = model.WebAccount(
        email="sync_progress@example.com", member_id=member.id, icon=""
    )
    session.add(wa)
    session.commit()

    mock_account = unittest.mock.MagicMock()
    # 初回受講年月: 2026年7月
    mock_account.get_first_lesson_date.return_value = datetime.datetime(
        2026, 7, 1, 10, 0
    )
    mock_account.get_lesson_history.return_value = create_dummy_month_history()

    progress_calls: list[tuple[int, int, int, int]] = []

    def on_progress(current: int, total: int, year: int, month: int) -> None:
        progress_calls.append((current, total, year, month))

    fixed_now = datetime.datetime(2026, 9, 21, 12, 0, 0)
    with unittest.mock.patch("streamlit_feelcycle.history.datetime") as mock_datetime:
        mock_datetime.datetime.now.return_value = fixed_now
        mock_datetime.datetime.combine = datetime.datetime.combine
        mock_datetime.datetime.side_effect = lambda *args, **kw: datetime.datetime(
            *args, **kw
        )

        result = history.sync_all_histories(
            mock_account, wa.id, session, on_progress=on_progress
        )

    # 2026年7月~9月の3か月分
    assert result["updated"] == 3
    assert len(progress_calls) == 3
    assert progress_calls == [
        (1, 3, 2026, 7),
        (2, 3, 2026, 8),
        (3, 3, 2026, 9),
    ]


# --- プログラム背景色・文字色の動的取得テスト ---
def test_extract_colors_from_calendar() -> None:
    # 正常一致
    sched = unittest.mock.MagicMock(
        sid_hash="target_sid", ibgcol="#123456", itxtcol="#abcdef"
    )
    l_list = unittest.mock.MagicMock(schedule=[sched])
    cal = unittest.mock.MagicMock(lesson_list=[l_list])

    bg, txt = history._extract_colors_from_calendar(cal, "target_sid")
    assert bg == "#123456"
    assert txt == "#abcdef"

    # 不一致
    bg, txt = history._extract_colors_from_calendar(cal, "other_sid")
    assert bg is None
    assert txt is None

    # None または空のカレンダー
    bg, txt = history._extract_colors_from_calendar(None, "target_sid")
    assert bg is None
    assert txt is None


def test_fetch_and_save_monthly_history_program_colors_success(
    session: sqlalchemy.orm.Session,
) -> None:
    member = model.Member(name="Color Test User")
    session.add(member)
    session.flush()
    wa = model.WebAccount(email="colortest@example.com", member_id=member.id, icon="")
    session.add(wa)
    session.commit()

    instructor = feelpycle.api.Instructor(id=101, name="Anna")
    prog_search = feelpycle.api.ProgramSearch(id=1, name="Color Prog 1")
    inst_search = feelpycle.api.InstructorSearch(id="101", name="Anna")

    lesson = feelpycle.api.LessonInfo(
        sid="color_sid_001",
        shift_date="2026/09/01",
        ls_st=datetime.time(10, 0, 0),
        ls_et=datetime.time(10, 45, 0),
        store_name="新宿",
        iname="Color Prog 1",
        instructor_name_list=[instructor],
        sheet_no=12,
        ticket_name="マンスリー30",
        program_search=prog_search,
        genre_search=[],
        instructor_search=inst_search,
        playlist_url="",
        cancel_flg=0,
        cancel_cancel_flg=0,
    )
    dummy_hist = feelpycle.api.MonthHistory(
        summary_count=1,
        member_count=1,
        ticket_count=0,
        lesson_info=[lesson],
    )

    # モックAccount
    mock_account = unittest.mock.MagicMock()
    mock_account.get_lesson_history.return_value = dummy_hist
    mock_account.get_studio_list.return_value = {10: "新宿", 20: "六本木"}

    sched = unittest.mock.MagicMock(
        sid_hash="color_sid_001", ibgcol="#ff55aa", itxtcol="#ffffff"
    )
    l_list = unittest.mock.MagicMock(schedule=[sched])
    cal_mock = unittest.mock.MagicMock(lesson_list=[l_list])

    # 実行
    with unittest.mock.patch.object(
        wrapper, "get_lesson_calendar", return_value=cal_mock
    ) as mock_get_lesson_calendar:
        res = history.fetch_and_save_monthly_history(
            mock_account, wa.id, 2026, 9, session
        )
        assert res is not None

        # wrapper.get_lesson_calendar が呼ばれたことを検証
        mock_get_lesson_calendar.assert_called_once_with(
            datetime.date(2026, 9, 1),
            10,
        )

    # Program レコードの背景色・文字色を検証
    prog = session.scalars(
        sqlalchemy.select(model.Program).where(model.Program.name == "Color Prog 1")
    ).first()
    assert prog is not None
    assert prog.background_color == "#ff55aa"
    assert prog.text_color == "#ffffff"


def test_fetch_and_save_monthly_history_program_colors_fallback(
    session: sqlalchemy.orm.Session,
) -> None:
    member = model.Member(name="Fallback Test User")
    session.add(member)
    session.flush()
    wa = model.WebAccount(
        email="fallbacktest@example.com", member_id=member.id, icon=""
    )
    session.add(wa)
    session.commit()

    instructor = feelpycle.api.Instructor(id=101, name="Anna")
    prog_search = feelpycle.api.ProgramSearch(id=2, name="Fallback Prog 1")
    inst_search = feelpycle.api.InstructorSearch(id="101", name="Anna")

    # 店舗名がスタジオ一覧にないケース
    lesson1 = feelpycle.api.LessonInfo(
        sid="fallback_sid_001",
        shift_date="2026/09/01",
        ls_st=datetime.time(10, 0, 0),
        ls_et=datetime.time(10, 45, 0),
        store_name="未知の店舗",
        iname="Fallback Prog 1",
        instructor_name_list=[instructor],
        sheet_no=12,
        ticket_name="マンスリー30",
        program_search=prog_search,
        genre_search=[],
        instructor_search=inst_search,
        playlist_url="",
        cancel_flg=0,
        cancel_cancel_flg=0,
    )

    prog_search2 = feelpycle.api.ProgramSearch(id=3, name="Fallback Prog 2")
    # API呼び出しで例外が発生するケース
    lesson2 = feelpycle.api.LessonInfo(
        sid="fallback_sid_002",
        shift_date="2026/09/02",
        ls_st=datetime.time(11, 0, 0),
        ls_et=datetime.time(11, 45, 0),
        store_name="銀座",
        iname="Fallback Prog 2",
        instructor_name_list=[instructor],
        sheet_no=15,
        ticket_name="マンスリー30",
        program_search=prog_search2,
        genre_search=[],
        instructor_search=inst_search,
        playlist_url="",
        cancel_flg=0,
        cancel_cancel_flg=0,
    )

    dummy_hist = feelpycle.api.MonthHistory(
        summary_count=2,
        member_count=1,
        ticket_count=0,
        lesson_info=[lesson1, lesson2],
    )

    mock_account = unittest.mock.MagicMock()
    mock_account.get_lesson_history.return_value = dummy_hist
    mock_account.get_studio_list.return_value = {30: "銀座"}
    # 銀座の呼び出しで例外
    mock_account.get_lesson_calendar_by_store.side_effect = RuntimeError("API Error")

    res = history.fetch_and_save_monthly_history(mock_account, wa.id, 2026, 9, session)
    assert res is not None

    # 未定義プログラムの場合は (None, None) で保存されること
    prog1 = session.scalars(
        sqlalchemy.select(model.Program).where(model.Program.name == "Fallback Prog 1")
    ).first()
    assert prog1 is not None
    assert prog1.background_color is None
    assert prog1.text_color is None

    prog2 = session.scalars(
        sqlalchemy.select(model.Program).where(model.Program.name == "Fallback Prog 2")
    ).first()
    assert prog2 is not None
    assert prog2.background_color is None
    assert prog2.text_color is None


def test_multiple_web_accounts_histories_and_summary(
    session: sqlalchemy.orm.Session,
) -> None:
    """同一会員に紐づく複数Webアカウントの履歴取得・サマリー集計・初回年月のテスト"""
    member = model.Member(name="Multi Account User")
    session.add(member)
    session.flush()

    wa1 = model.WebAccount(
        email="account1@example.com",
        member_id=member.id,
        icon="🚴",
    )
    wa2 = model.WebAccount(
        email="account2@example.com",
        member_id=member.id,
        icon="⭐",
    )
    session.add_all([wa1, wa2])
    session.flush()

    prog = model.Program(
        name="BB2 Multi",
        background_color="#FF9933",
        text_color="#000000",
    )
    session.add(prog)
    session.flush()

    # レッスン1 (wa2用: 2024年5月 初回)
    lesson_old = model.Lesson(
        sid="multi_sid_old",
        store_id=1,
        store_name="六本木",
        instructor_id_1=10,
        instructor_name_1="Taro",
        start_at=datetime.datetime(2024, 5, 10, 10, 0, 0),
        end_at=datetime.datetime(2024, 5, 10, 10, 45, 0),
        program_id=prog.id,
    )
    # レッスン2 (wa1用: 2026年9月1日 10:00 マンスリー)
    lesson_sep1 = model.Lesson(
        sid="multi_sid_sep1",
        store_id=1,
        store_name="六本木",
        instructor_id_1=10,
        instructor_name_1="Taro",
        start_at=datetime.datetime(2026, 9, 1, 10, 0, 0),
        end_at=datetime.datetime(2026, 9, 1, 10, 45, 0),
        program_id=prog.id,
    )
    # レッスン3 (wa2用: 2026年9月5日 19:00 チケット)
    lesson_sep2 = model.Lesson(
        sid="multi_sid_sep2",
        store_id=2,
        store_name="銀座",
        instructor_id_1=20,
        instructor_name_1="Hanako",
        start_at=datetime.datetime(2026, 9, 5, 19, 0, 0),
        end_at=datetime.datetime(2026, 9, 5, 19, 45, 0),
        program_id=prog.id,
    )
    session.add_all([lesson_old, lesson_sep1, lesson_sep2])
    session.flush()

    hist_old = model.LessonHistory(
        web_account_id=wa2.id,
        lesson_sid=lesson_old.sid,
        bike_number="01",
        ticket_type="マンスリー",
        is_absent=False,
    )
    hist_sep1 = model.LessonHistory(
        web_account_id=wa1.id,
        lesson_sid=lesson_sep1.sid,
        bike_number="12",
        ticket_type="マンスリー",
        is_absent=False,
    )
    hist_sep2 = model.LessonHistory(
        web_account_id=wa2.id,
        lesson_sid=lesson_sep2.sid,
        bike_number="05",
        ticket_type="チケット",
        is_absent=False,
    )
    session.add_all([hist_old, hist_sep1, hist_sep2])
    session.commit()

    wa_ids = [wa1.id, wa2.id]

    # 1. 履歴一覧取得のテスト (アカウント列と昇順ソートの検証)
    histories_sep = history.get_monthly_histories_from_db(wa_ids, 2026, 9, session)
    assert len(histories_sep) == 2
    assert histories_sep[0]["アカウント"] == "🚴"
    assert histories_sep[0]["受講日"] == "2026/09/01"
    assert histories_sep[0]["バイク"] == "12"
    assert histories_sep[1]["アカウント"] == "⭐"
    assert histories_sep[1]["受講日"] == "2026/09/05"
    assert histories_sep[1]["バイク"] == "05"

    # 2. サマリー集計のテスト (2アカウント合算)
    summary_sep = history.get_monthly_summary(wa_ids, 2026, 9, session)
    assert summary_sep["monthly_count"] == 2
    assert summary_sep["member_count"] == 1
    assert summary_sep["ticket_count"] == 1
    assert summary_sep["total_count"] == 3  # 過去の1回も含めて合計3回

    # 3. 初回受講年月のテスト (wa2 の 2024年5月 が返ること)
    first_ym = history.get_first_lesson_year_month(None, wa_ids, session)
    assert first_ym == (2024, 5)

    # 4. アイコン未設定時はメールアドレスではなく 🚴 が返ることのテスト
    wa2.icon = ""
    session.commit()
    histories_unset = history.get_monthly_histories_from_db([wa2.id], 2026, 9, session)
    assert histories_unset[0]["アカウント"] == "🚴"


def test_generate_and_parse_period_options() -> None:
    # 期間オプションの生成テスト
    options = history.generate_period_options(2024, 4, 2026, 10)
    assert options[0] == "全期間"
    assert options[1] == "2026年全体"
    assert options[2] == "2026年10月"
    assert "2026年1月" in options
    assert "2025年全体" in options
    assert "2025年12月" in options
    assert "2025年1月" in options
    assert "2024年全体" in options
    assert "2024年4月" in options
    assert "2024年3月" not in options
    assert "2026年11月" not in options

    # 順序の検証 (2026年全体 -> 2026年10月 -> ... -> 2025年全体 -> ...)
    idx_2026_all = options.index("2026年全体")
    idx_2026_10 = options.index("2026年10月")
    idx_2026_1 = options.index("2026年1月")
    idx_2025_all = options.index("2025年全体")
    idx_2024_4 = options.index("2024年4月")
    assert idx_2026_all < idx_2026_10 < idx_2026_1 < idx_2025_all < idx_2024_4

    # 期間オプションの解析テスト
    assert history.parse_period_option("全期間") == (None, None)
    assert history.parse_period_option("2026年全体") == (2026, None)
    assert history.parse_period_option("2026年10月") == (2026, 10)
    assert history.parse_period_option("無効な文字列") == (None, None)


def test_summary_functions_with_filters_and_order(
    session: sqlalchemy.orm.Session,
) -> None:
    # ユーザーとプログラムの作成
    member = model.Member(name="Summary Test User")
    session.add(member)
    session.flush()

    wa = model.WebAccount(email="summary@example.com", member_id=member.id, icon="🚴")
    session.add(wa)
    session.flush()

    prog1 = model.Program(name="BB2 MLN 2", background_color="#000", text_color="#fff")
    prog2 = model.Program(name="BSW Hit 8", background_color="#111", text_color="#eee")
    session.add_all([prog1, prog2])
    session.flush()

    # レッスンの作成 (2025年に1回、2026年に2回)
    # Anna: 2回 (2025年と2026年9月), Bob: 1回 (2026年10月)
    # BB2 MLN 2: 2回, BSW Hit 8: 1回
    lesson_2025 = model.Lesson(
        sid="sid_2025",
        store_id=1,
        store_name="新宿",
        instructor_id_1=101,
        instructor_name_1="Anna",
        instructor_id_2=None,
        instructor_name_2=None,
        start_at=datetime.datetime(2025, 12, 1, 10, 0),
        end_at=datetime.datetime(2025, 12, 1, 10, 45),
        program_id=prog1.id,
    )
    lesson_2026_sep = model.Lesson(
        sid="sid_2026_sep",
        store_id=1,
        store_name="新宿",
        instructor_id_1=101,
        instructor_name_1="Anna",
        instructor_id_2=None,
        instructor_name_2=None,
        start_at=datetime.datetime(2026, 9, 15, 11, 0),
        end_at=datetime.datetime(2026, 9, 15, 11, 45),
        program_id=prog1.id,
    )
    lesson_2026_oct = model.Lesson(
        sid="sid_2026_oct",
        store_id=2,
        store_name="六本木",
        instructor_id_1=102,
        instructor_name_1="Bob",
        instructor_id_2=None,
        instructor_name_2=None,
        start_at=datetime.datetime(2026, 10, 1, 12, 0),
        end_at=datetime.datetime(2026, 10, 1, 12, 45),
        program_id=prog2.id,
    )
    session.add_all([lesson_2025, lesson_2026_sep, lesson_2026_oct])
    session.flush()

    hist1 = model.LessonHistory(
        web_account_id=wa.id,
        lesson_sid=lesson_2025.sid,
        bike_number="01",
        ticket_type="マンスリー",
        is_absent=False,
    )
    hist2 = model.LessonHistory(
        web_account_id=wa.id,
        lesson_sid=lesson_2026_sep.sid,
        bike_number="02",
        ticket_type="マンスリー",
        is_absent=False,
    )
    hist3 = model.LessonHistory(
        web_account_id=wa.id,
        lesson_sid=lesson_2026_oct.sid,
        bike_number="03",
        ticket_type="マンスリー",
        is_absent=False,
    )
    session.add_all([hist1, hist2, hist3])
    session.commit()

    wa_ids = [wa.id]

    # 全期間集計 (order_by_count=True)
    inst_all = history.get_instructor_summary(wa_ids, session, order_by_count=True)
    assert len(inst_all) == 2
    assert inst_all[0]["Instructor"] == "Anna"
    assert inst_all[0]["count"] == 2
    assert inst_all[1]["Instructor"] == "Bob"
    assert inst_all[1]["count"] == 1

    # 年単位集計 (2026年全体)
    inst_2026 = history.get_instructor_summary(
        wa_ids, session, year=2026, order_by_count=True
    )
    assert len(inst_2026) == 2
    # 2026年はAnna 1回, Bob 1回
    assert {row["Instructor"] for row in inst_2026} == {"Anna", "Bob"}

    # 年月単位集計 (2026年10月)
    inst_2026_10 = history.get_instructor_summary(
        wa_ids, session, year=2026, month=10, order_by_count=True
    )
    assert len(inst_2026_10) == 1
    assert inst_2026_10[0]["Instructor"] == "Bob"
    assert inst_2026_10[0]["count"] == 1

    # プログラム集計 (2026年全体, order_by_count=True)
    prog_2026 = history.get_program_summary(
        wa_ids, session, year=2026, order_by_count=True
    )
    assert len(prog_2026) == 2

    # スタジオ集計 (2026年全体)
    studio_2026 = history.get_studio_summary(wa_ids, session, year=2026)
    assert len(studio_2026) == 2
    assert {row["Studio"] for row in studio_2026} == {"新宿", "六本木"}

    # 総受講回数集計 (get_total_lesson_count)
    assert history.get_total_lesson_count(wa_ids, session) == 3
    assert history.get_total_lesson_count(wa_ids, session, year=2026) == 2
    assert history.get_total_lesson_count(wa_ids, session, year=2026, month=10) == 1
    assert history.get_total_lesson_count(wa_ids, session, year=2025) == 1
    assert history.get_total_lesson_count(wa_ids, session, year=2024) == 0


def test_get_instructor_summary_with_instructor_2(
    session: sqlalchemy.orm.Session,
) -> None:
    member = model.Member(name="Instructor 2 Test User")
    session.add(member)
    session.flush()

    wa = model.WebAccount(email="instructor2_test@example.com", member_id=member.id)
    session.add(wa)
    session.flush()

    prog = model.Program(name="BB2 Test", background_color="#000", text_color="#fff")
    session.add(prog)
    session.flush()

    # レッスン1: 2026-05-01, Main: Anna, Sub: Bob
    lesson1 = model.Lesson(
        sid="sid_sub_1",
        store_id=1,
        store_name="銀座",
        instructor_id_1=101,
        instructor_name_1="Anna",
        instructor_id_2=102,
        instructor_name_2="Bob",
        start_at=datetime.datetime(2026, 5, 1, 10, 0),
        end_at=datetime.datetime(2026, 5, 1, 10, 45),
        program_id=prog.id,
    )
    # レッスン2: 2026-06-01, Main: Bob, Sub: None
    lesson2 = model.Lesson(
        sid="sid_sub_2",
        store_id=1,
        store_name="銀座",
        instructor_id_1=102,
        instructor_name_1="Bob",
        instructor_id_2=None,
        instructor_name_2=None,
        start_at=datetime.datetime(2026, 6, 1, 11, 0),
        end_at=datetime.datetime(2026, 6, 1, 11, 45),
        program_id=prog.id,
    )
    # レッスン3: 2026-07-01, Main: Charlie, Sub: Anna
    lesson3 = model.Lesson(
        sid="sid_sub_3",
        store_id=1,
        store_name="銀座",
        instructor_id_1=103,
        instructor_name_1="Charlie",
        instructor_id_2=101,
        instructor_name_2="Anna",
        start_at=datetime.datetime(2026, 7, 1, 12, 0),
        end_at=datetime.datetime(2026, 7, 1, 12, 45),
        program_id=prog.id,
    )
    # レッスン4: 2026-08-01, Main: David, Sub: Bob (キャンセル/欠席)
    lesson4 = model.Lesson(
        sid="sid_sub_4",
        store_id=1,
        store_name="銀座",
        instructor_id_1=104,
        instructor_name_1="David",
        instructor_id_2=102,
        instructor_name_2="Bob",
        start_at=datetime.datetime(2026, 8, 1, 13, 0),
        end_at=datetime.datetime(2026, 8, 1, 13, 45),
        program_id=prog.id,
    )
    session.add_all([lesson1, lesson2, lesson3, lesson4])
    session.flush()

    hist1 = model.LessonHistory(
        web_account_id=wa.id,
        lesson_sid=lesson1.sid,
        bike_number="01",
        is_absent=False,
    )
    hist2 = model.LessonHistory(
        web_account_id=wa.id,
        lesson_sid=lesson2.sid,
        bike_number="02",
        is_absent=False,
    )
    hist3 = model.LessonHistory(
        web_account_id=wa.id,
        lesson_sid=lesson3.sid,
        bike_number="03",
        is_absent=False,
    )
    hist4 = model.LessonHistory(
        web_account_id=wa.id,
        lesson_sid=lesson4.sid,
        bike_number="04",
        is_absent=True,
    )
    session.add_all([hist1, hist2, hist3, hist4])
    session.commit()

    wa_ids = [wa.id]

    # 全期間集計 (order_by_count=True)
    summary_all = history.get_instructor_summary(wa_ids, session, order_by_count=True)
    assert len(summary_all) == 3
    # Anna: 2回 (lesson1のメイン + lesson3のサブ)
    # Bob: 2回 (lesson1のサブ + lesson2のメイン), Charlie: 1回
    summary_dict = {row["Instructor"]: row for row in summary_all}
    assert summary_dict["Anna"]["count"] == 2
    assert summary_dict["Anna"]["First taken"] == "2026/05/01"
    assert summary_dict["Bob"]["count"] == 2
    assert summary_dict["Bob"]["First taken"] == "2026/05/01"
    assert summary_dict["Charlie"]["count"] == 1
    assert summary_dict["Charlie"]["First taken"] == "2026/07/01"
    assert "David" not in summary_dict

    # 2026年5月集計 (lesson1のみ: Annaメイン, Bobサブ)
    summary_may = history.get_instructor_summary(
        wa_ids, session, year=2026, month=5, order_by_count=True
    )
    assert len(summary_may) == 2
    may_dict = {row["Instructor"]: row for row in summary_may}
    assert may_dict["Anna"]["count"] == 1
    assert may_dict["Bob"]["count"] == 1

    # order_by_count=False (first_taken順)
    summary_asc = history.get_instructor_summary(wa_ids, session, order_by_count=False)
    assert len(summary_asc) == 3
    # lesson1 (5/1) で受講したAnna, Bobが先に来て、Charlie (7/1) が最後
    assert summary_asc[2]["Instructor"] == "Charlie"
