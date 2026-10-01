import datetime
import typing

import pytest
import sqlalchemy
import sqlalchemy.orm

import streamlit_feelcycle.model


@pytest.fixture
def session() -> typing.Generator[sqlalchemy.orm.Session, None, None]:
    engine = sqlalchemy.create_engine("sqlite:///:memory:")
    streamlit_feelcycle.model.Base.metadata.create_all(engine)
    Session = sqlalchemy.orm.sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_member_crud(session: sqlalchemy.orm.Session) -> None:
    # 作成
    member = streamlit_feelcycle.model.Member(name="山田太郎")
    session.add(member)
    session.commit()

    # 取得
    stmt = sqlalchemy.select(streamlit_feelcycle.model.Member).where(
        streamlit_feelcycle.model.Member.name == "山田太郎"
    )
    db_member = session.scalars(stmt).first()
    assert db_member is not None
    assert db_member.id == 1
    assert db_member.name == "山田太郎"

    # 更新
    db_member.name = "山田花子"
    session.commit()

    stmt_updated = sqlalchemy.select(streamlit_feelcycle.model.Member).where(
        streamlit_feelcycle.model.Member.id == 1
    )
    db_member_updated = session.scalars(stmt_updated).first()
    assert db_member_updated is not None
    assert db_member_updated.name == "山田花子"

    # 削除
    session.delete(db_member_updated)
    session.commit()

    stmt_deleted = sqlalchemy.select(streamlit_feelcycle.model.Member).where(
        streamlit_feelcycle.model.Member.id == 1
    )
    assert session.scalars(stmt_deleted).first() is None


def test_web_account_relation(session: sqlalchemy.orm.Session) -> None:
    # Member と WebAccount の作成
    member = streamlit_feelcycle.model.Member(name="田中次郎")
    session.add(member)
    session.commit()

    web_account = streamlit_feelcycle.model.WebAccount(
        email="jiro@example.com",
        member_id=member.id,
        icon="🚴",
    )
    session.add(web_account)
    session.commit()

    # リレーションシップの検証
    stmt = sqlalchemy.select(streamlit_feelcycle.model.WebAccount).where(
        streamlit_feelcycle.model.WebAccount.email == "jiro@example.com"
    )
    db_web_account = session.scalars(stmt).first()
    assert db_web_account is not None
    assert db_web_account.member.name == "田中次郎"
    assert len(db_web_account.member.web_accounts) == 1
    assert db_web_account.member.web_accounts[0].email == "jiro@example.com"


def test_lesson_and_history(session: sqlalchemy.orm.Session) -> None:
    # 依存データの準備
    member = streamlit_feelcycle.model.Member(name="鈴木一郎")
    session.add(member)
    session.commit()

    web_account = streamlit_feelcycle.model.WebAccount(
        email="ichiro@example.com",
        member_id=member.id,
        icon="🏃",
    )
    session.add(web_account)

    program = streamlit_feelcycle.model.Program(
        name="BB2 MLN 2",
        background_color="#000000",
        text_color="#FFFFFF",
    )
    session.add(program)
    session.commit()

    # レッスンの作成
    start_time = datetime.datetime.now()
    end_time = start_time + datetime.timedelta(minutes=45)
    lesson = streamlit_feelcycle.model.Lesson(
        sid="dummy_sid_hash_1234567890",
        store_id=1,
        store_name="店舗A",
        instructor_id_1=101,
        instructor_name_1="インスラA",
        instructor_id_2=None,
        instructor_name_2=None,
        start_at=start_time,
        end_at=end_time,
        program_id=program.id,
    )
    session.add(lesson)
    session.commit()

    # 受講履歴の作成
    history = streamlit_feelcycle.model.LessonHistory(
        web_account_id=web_account.id,
        lesson_sid=lesson.sid,
        bike_number="12",
        ticket_type="マンスリー",
        is_absent=False,
    )
    session.add(history)
    session.commit()

    # 検証
    stmt = sqlalchemy.select(streamlit_feelcycle.model.LessonHistory).where(
        streamlit_feelcycle.model.LessonHistory.bike_number == "12"
    )
    db_history = session.scalars(stmt).first()
    assert db_history is not None
    assert db_history.web_account.email == "ichiro@example.com"
    assert db_history.lesson.sid == "dummy_sid_hash_1234567890"
    assert db_history.lesson.program.name == "BB2 MLN 2"
    assert db_history.lesson.updated_at is not None
    assert db_history.is_absent is False


def test_web_account_history_update_crud(
    session: sqlalchemy.orm.Session,
) -> None:
    # 準備
    member = streamlit_feelcycle.model.Member(name="更新テスト太郎")
    session.add(member)
    session.commit()

    web_account = streamlit_feelcycle.model.WebAccount(
        email="update_test@example.com",
        member_id=member.id,
        icon="🚴",
    )
    session.add(web_account)
    session.commit()

    # 作成
    now = datetime.datetime.now()
    history_update = streamlit_feelcycle.model.WebAccountHistoryUpdate(
        web_account_id=web_account.id,
        year=2024,
        month=8,
        last_updated_time=now,
    )
    session.add(history_update)
    session.commit()

    # 取得
    stmt = sqlalchemy.select(streamlit_feelcycle.model.WebAccountHistoryUpdate).where(
        streamlit_feelcycle.model.WebAccountHistoryUpdate.web_account_id
        == web_account.id,
        streamlit_feelcycle.model.WebAccountHistoryUpdate.year == 2024,
        streamlit_feelcycle.model.WebAccountHistoryUpdate.month == 8,
    )
    db_update = session.scalars(stmt).first()
    assert db_update is not None
    assert db_update.web_account_id == web_account.id
    assert db_update.year == 2024
    assert db_update.month == 8
    assert db_update.web_account.email == "update_test@example.com"
    assert len(web_account.history_updates) == 1
    assert web_account.history_updates[0].year == 2024

    # 複合主キーで別レコード追加
    history_update_next = streamlit_feelcycle.model.WebAccountHistoryUpdate(
        web_account_id=web_account.id,
        year=2024,
        month=9,
        last_updated_time=now,
    )
    session.add(history_update_next)
    session.commit()
    assert len(web_account.history_updates) == 2

    # 削除
    session.delete(db_update)
    session.commit()

    db_update_deleted = session.scalars(stmt).first()
    assert db_update_deleted is None
