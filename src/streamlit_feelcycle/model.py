import datetime
import typing

import sqlalchemy
import sqlalchemy.orm


class Base(sqlalchemy.orm.DeclarativeBase):
    pass


class Member(Base):
    """会員"""

    __tablename__ = "members"

    id: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        primary_key=True, autoincrement=True
    )
    name: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(20), nullable=False
    )

    # Relationships
    web_accounts: sqlalchemy.orm.Mapped[list["WebAccount"]] = (
        sqlalchemy.orm.relationship(back_populates="member")
    )


class WebAccount(Base):
    """Webメンバーアカウント"""

    __tablename__ = "web_accounts"

    id: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        primary_key=True, autoincrement=True
    )
    email: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(50), unique=True, index=True, nullable=False
    )
    member_id: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        sqlalchemy.ForeignKey("members.id"), index=True, nullable=False
    )
    icon: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(8), nullable=False, default="🚴"
    )

    # Relationships
    member: sqlalchemy.orm.Mapped["Member"] = sqlalchemy.orm.relationship(
        back_populates="web_accounts"
    )
    histories: sqlalchemy.orm.Mapped[list["LessonHistory"]] = (
        sqlalchemy.orm.relationship(
            back_populates="web_account",
            cascade="all, delete-orphan",
        )
    )
    history_updates: sqlalchemy.orm.Mapped[list["WebAccountHistoryUpdate"]] = (
        sqlalchemy.orm.relationship(
            back_populates="web_account",
            cascade="all, delete-orphan",
        )
    )


class Program(Base):
    """プログラム"""

    __tablename__ = "programs"

    id: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        primary_key=True, autoincrement=True
    )
    name: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(12), unique=True, index=True, nullable=False
    )
    background_color: sqlalchemy.orm.Mapped[typing.Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(20), nullable=True)
    )
    text_color: sqlalchemy.orm.Mapped[typing.Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(20), nullable=True)
    )

    # Relationships
    lessons: sqlalchemy.orm.Mapped[list["Lesson"]] = sqlalchemy.orm.relationship(
        back_populates="program"
    )


class Lesson(Base):
    """レッスン"""

    __tablename__ = "lessons"

    sid: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(160), primary_key=True
    )
    store_id: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        index=True, nullable=False
    )
    store_name: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(20), nullable=False
    )
    instructor_id_1: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        nullable=False
    )
    instructor_name_1: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(20), nullable=False
    )
    instructor_id_2: sqlalchemy.orm.Mapped[typing.Optional[int]] = (
        sqlalchemy.orm.mapped_column(nullable=True)
    )
    instructor_name_2: sqlalchemy.orm.Mapped[typing.Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(20), nullable=True)
    )
    start_at: sqlalchemy.orm.Mapped[datetime.datetime] = sqlalchemy.orm.mapped_column(
        index=True, nullable=False
    )
    end_at: sqlalchemy.orm.Mapped[datetime.datetime] = sqlalchemy.orm.mapped_column(
        nullable=False
    )
    program_id: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        sqlalchemy.ForeignKey("programs.id"), index=True, nullable=False
    )
    updated_at: sqlalchemy.orm.Mapped[datetime.datetime] = sqlalchemy.orm.mapped_column(
        nullable=False,
        server_default=sqlalchemy.func.now(),
        onupdate=sqlalchemy.func.now(),
    )

    # Relationships
    program: sqlalchemy.orm.Mapped["Program"] = sqlalchemy.orm.relationship(
        back_populates="lessons"
    )
    histories: sqlalchemy.orm.Mapped[list["LessonHistory"]] = (
        sqlalchemy.orm.relationship(back_populates="lesson")
    )


class LessonHistory(Base):
    """レッスン受講履歴"""

    __tablename__ = "lesson_histories"

    id: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        primary_key=True, autoincrement=True
    )
    web_account_id: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        sqlalchemy.ForeignKey("web_accounts.id"), index=True, nullable=False
    )
    lesson_sid: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(160),
        sqlalchemy.ForeignKey("lessons.sid"),
        index=True,
        nullable=False,
    )
    bike_number: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(20), nullable=False
    )
    ticket_type: sqlalchemy.orm.Mapped[typing.Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(100), nullable=True)
    )
    is_absent: sqlalchemy.orm.Mapped[bool] = sqlalchemy.orm.mapped_column(
        nullable=False, default=False
    )

    # Relationships
    web_account: sqlalchemy.orm.Mapped["WebAccount"] = sqlalchemy.orm.relationship(
        back_populates="histories"
    )
    lesson: sqlalchemy.orm.Mapped["Lesson"] = sqlalchemy.orm.relationship(
        back_populates="histories"
    )


class WebAccountHistoryUpdate(Base):
    """Webメンバーアカウント受講履歴更新履歴"""

    __tablename__ = "web_account_history_updates"

    web_account_id: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        sqlalchemy.ForeignKey("web_accounts.id"),
        primary_key=True,
        index=True,
        nullable=False,
    )
    year: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        primary_key=True, nullable=False
    )
    month: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        primary_key=True, nullable=False
    )
    last_updated_time: sqlalchemy.orm.Mapped[datetime.datetime] = (
        sqlalchemy.orm.mapped_column(
            nullable=False,
            server_default=sqlalchemy.func.now(),
            onupdate=sqlalchemy.func.now(),
        )
    )

    # Relationships
    web_account: sqlalchemy.orm.Mapped["WebAccount"] = sqlalchemy.orm.relationship(
        back_populates="history_updates"
    )
