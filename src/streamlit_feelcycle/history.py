import datetime
import logging
import typing

import dateutil.relativedelta
import feelpycle.api
import pandas
import pandas.io.formats.style
import sqlalchemy
import sqlalchemy.orm

import streamlit_feelcycle.model as model
import streamlit_feelcycle.program as program
import streamlit_feelcycle.wrapper as wrapper

LOGGER = logging.getLogger(__name__)


def should_update_month(
    web_account_id: int,
    year: int,
    month: int,
    now: datetime.datetime,
    session: sqlalchemy.orm.Session,
) -> bool:
    """指定月の受講履歴をAPIから再取得すべきかを判定する。

    以下のいずれかに該当する場合に True を返す:
    1. 対象月の更新履歴が web_account_history_updates にレコードなし
    2. 対象の月の更新月が次の月以降ではない (更新月 < 次の月)
    3. 対象の月の更新日時が最終更新から4か月以上経過している
    """
    # DB から更新履歴を取得
    stmt = sqlalchemy.select(model.WebAccountHistoryUpdate).where(
        model.WebAccountHistoryUpdate.web_account_id == web_account_id,
        model.WebAccountHistoryUpdate.year == year,
        model.WebAccountHistoryUpdate.month == month,
    )
    update_record = session.scalars(stmt).first()

    # 条件1: レコードが存在しない (未取得) → 更新対象
    if update_record is None:
        return True

    # 次の月を算出
    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1

    updated_year = update_record.last_updated_time.year
    updated_month = update_record.last_updated_time.month

    # 条件2: 更新月が次の月以降ではない (例: 対象が9月で更新月が9月以前) → 更新対象
    if (updated_year, updated_month) < (next_year, next_month):
        return True

    # 条件3: 最終更新から4か月以上経過 → 更新対象
    threshold = now - dateutil.relativedelta.relativedelta(months=4)
    if update_record.last_updated_time <= threshold:
        return True

    return False


def upsert_history_update(
    web_account_id: int,
    year: int,
    month: int,
    now: datetime.datetime,
    session: sqlalchemy.orm.Session,
) -> None:
    """web_account_history_updates テーブルに更新履歴を upsert する。"""
    stmt = sqlalchemy.select(model.WebAccountHistoryUpdate).where(
        model.WebAccountHistoryUpdate.web_account_id == web_account_id,
        model.WebAccountHistoryUpdate.year == year,
        model.WebAccountHistoryUpdate.month == month,
    )
    record = session.scalars(stmt).first()
    if record is None:
        record = model.WebAccountHistoryUpdate(
            web_account_id=web_account_id,
            year=year,
            month=month,
            last_updated_time=now,
        )
        session.add(record)
    else:
        record.last_updated_time = now


def sync_all_histories(
    account: feelpycle.api.Account,
    web_account_id: int,
    session: sqlalchemy.orm.Session,
    on_progress: typing.Optional[typing.Callable[[int, int, int, int], None]] = None,
) -> dict[str, int]:
    """ログイン直後に呼び出し、全対象月の受講履歴を一括更新する。

    初回受講年月から現在年月までの全月を走査し、更新条件に該当する月のみ
    APIから取得してDBに保存する。

    Args:
        account: feelpycle APIアカウントインスタンス
        web_account_id: 対象のWebアカウントID
        session: DBセッション
        on_progress: 進捗通知用コールバック関数 (current, total, year, month) -> None

    Returns:
        更新結果のサマリー dict:
        - "updated": 更新に成功した月数
        - "skipped": スキップした月数
        - "failed": 更新に失敗した月数
    """
    now = datetime.datetime.now()
    first_year, first_month = get_first_lesson_year_month(
        account=account,
        web_account_id=web_account_id,
        session=session,
    )

    # 初回受講年月から現在年月まで全月を列挙
    updated = 0
    skipped = 0
    failed = 0

    # 店舗名逆引き辞書の事前準備
    store_name_to_id: dict[str, int] = {}
    try:
        studios = account.get_studio_list()
        if isinstance(studios, dict):
            store_name_to_id = {v: k for k, v in studios.items()}
    except Exception as e:
        LOGGER.warning(f"Failed to fetch studio list from API: {e}")

    start_ym = feelpycle.api.YearMonth(first_year, first_month)
    end_ym = feelpycle.api.YearMonth(now.year, now.month)
    total_months = max(1, end_ym.month_serial_ - start_ym.month_serial_ + 1)

    for processed_count, ym in enumerate(
        feelpycle.api.YearMonth.range(start_ym, end_ym), start=1
    ):
        current_year, current_month = ym.year_month()
        if on_progress is not None:
            on_progress(processed_count, total_months, current_year, current_month)

        if should_update_month(
            web_account_id, current_year, current_month, now, session
        ):
            LOGGER.info(f"Updating history for {current_year}/{current_month:02d}")
            fetch_and_save_monthly_history(
                account,
                web_account_id,
                current_year,
                current_month,
                session,
                store_name_to_id=store_name_to_id,
            )
            # 受講履歴がない月 (API戻り値が None や空) でも「更新した」とみなして更新履歴を記録
            upsert_history_update(
                web_account_id, current_year, current_month, now, session
            )
            session.commit()
            updated += 1
        else:
            skipped += 1

    LOGGER.info(
        f"History sync complete: updated={updated}, skipped={skipped}, failed={failed}"
    )
    return {"updated": updated, "skipped": skipped, "failed": failed}


def _extract_colors_from_calendar(
    calendar: typing.Any, sid: str
) -> tuple[typing.Optional[str], typing.Optional[str]]:
    """カレンダー情報から指定SIDのレッスンの背景色と文字色を抽出する。"""
    if not calendar or not hasattr(calendar, "lesson_list"):
        return None, None
    for l_list in calendar.lesson_list:
        for sched in getattr(l_list, "schedule", []):
            if getattr(sched, "sid_hash", None) == sid:
                return getattr(sched, "ibgcol", None), getattr(sched, "itxtcol", None)
    return None, None


def fetch_and_save_monthly_history(
    account: feelpycle.api.Account,
    web_account_id: int,
    year: int,
    month: int,
    session: sqlalchemy.orm.Session,
    store_name_to_id: typing.Optional[dict[str, int]] = None,
) -> typing.Optional[feelpycle.api.MonthHistory]:
    """Feelcycle APIから指定年月の受講履歴を取得し、DBに保存・更新する。"""
    try:
        month_history = account.get_lesson_history(year, month)
    except Exception as e:
        LOGGER.error(f"Failed to fetch lesson history from API: {e}")
        return None

    if not month_history:
        return None

    if store_name_to_id is None:
        try:
            studios = account.get_studio_list()
            if isinstance(studios, dict):
                store_name_to_id = {v: k for k, v in studios.items()}
            else:
                store_name_to_id = {}
        except Exception as e:
            LOGGER.warning(f"Failed to fetch studio list from API: {e}")
            store_name_to_id = {}

    for lesson_info in month_history.lesson_info:
        # 1. Programの登録または取得
        program_name = lesson_info.iname
        stmt_program = sqlalchemy.select(model.Program).where(
            model.Program.name == program_name
        )
        store_id = store_name_to_id.get(lesson_info.store_name)
        if store_id is None:
            for name, stid in store_name_to_id.items():
                if name in lesson_info.store_name or lesson_info.store_name in name:
                    store_id = stid
                    break

        program_record = session.scalars(stmt_program).first()
        if not program_record:
            background_color = None
            text_color = None

            if store_id is not None:
                try:
                    cal = wrapper.get_lesson_calendar(lesson_info.shift_date, store_id)

                    background_color, text_color = _extract_colors_from_calendar(
                        cal, lesson_info.sid
                    )
                except Exception as e:
                    LOGGER.warning(
                        f"Failed to fetch lesson calendar for store_id={store_id}, "
                        f"date={lesson_info.shift_date}: {e}"
                    )

            # Fallback to colors_of()
            if background_color is None or text_color is None:
                background_color, text_color = program.colors_of(program_name)

            program_record = model.Program(
                name=program_name,
                background_color=background_color,
                text_color=text_color,
            )
            session.add(program_record)
            session.flush()

        # 2. Lessonの登録または更新
        start_at = datetime.datetime.combine(lesson_info.shift_date, lesson_info.ls_st)
        end_at = datetime.datetime.combine(lesson_info.shift_date, lesson_info.ls_et)
        inst_id_1 = (
            lesson_info.instructor_name_list[0].id
            if lesson_info.instructor_name_list
            else 0
        )
        inst_name_1 = (
            lesson_info.instructor_name_list[0].name
            if lesson_info.instructor_name_list
            else ""
        )
        inst_id_2 = (
            lesson_info.instructor_name_list[1].id
            if len(lesson_info.instructor_name_list) > 1
            else None
        )
        inst_name_2 = (
            lesson_info.instructor_name_list[1].name
            if len(lesson_info.instructor_name_list) > 1
            else None
        )

        stmt_lesson = sqlalchemy.select(model.Lesson).where(
            model.Lesson.sid == lesson_info.sid
        )
        lesson = session.scalars(stmt_lesson).first()
        if not lesson:
            lesson = model.Lesson(
                sid=lesson_info.sid,
                store_id=store_id or 0,
                store_name=lesson_info.store_name,
                instructor_id_1=inst_id_1,
                instructor_name_1=inst_name_1,
                instructor_id_2=inst_id_2,
                instructor_name_2=inst_name_2,
                start_at=start_at,
                end_at=end_at,
                program_id=program_record.id,
            )
            session.add(lesson)
            session.flush()
        else:
            lesson.store_name = lesson_info.store_name
            lesson.instructor_id_1 = inst_id_1
            lesson.instructor_name_1 = inst_name_1
            lesson.instructor_id_2 = inst_id_2
            lesson.instructor_name_2 = inst_name_2
            lesson.start_at = start_at
            lesson.end_at = end_at
            lesson.program_id = program_record.id

        # 3. LessonHistoryの登録または更新
        is_absent = lesson_info.cancel_flg != 0
        stmt_history = sqlalchemy.select(model.LessonHistory).where(
            model.LessonHistory.web_account_id == web_account_id,
            model.LessonHistory.lesson_sid == lesson_info.sid,
        )
        history = session.scalars(stmt_history).first()
        if not history:
            history = model.LessonHistory(
                web_account_id=web_account_id,
                lesson_sid=lesson_info.sid,
                bike_number=str(lesson_info.sheet_no),
                ticket_type=lesson_info.ticket_name,
                is_absent=is_absent,
            )
            session.add(history)
        else:
            history.bike_number = str(lesson_info.sheet_no)
            history.ticket_type = lesson_info.ticket_name
            history.is_absent = is_absent

    session.commit()
    return month_history


DEFAULT_ACCOUNT_ICONS: list[str] = [
    "🚴",
    "🚲",
    "✨",
    "😄",
    "😊",
    "😺",
    "👤",
    "🐶",
    "🍎",
    "⚡",
    "🌟",
    "🔥",
    "💘",
    "💕",
    "👟",
    "🎵",
    "🎧",
    "🎹",
]


def get_valid_lesson_history_filters() -> list[typing.Any]:
    """集計・表示対象となる有効なLessonHistoryのSQLAlchemyフィルター条件を返す。

    以下の条件の両方を満たすレコードを除外する:
    - bike_number が "0"
    - ticket_type が空文字 (null は除外しない)
    """
    return [
        sqlalchemy.or_(
            model.LessonHistory.bike_number != "0",
            model.LessonHistory.ticket_type.is_(None),
            model.LessonHistory.ticket_type != "",
        ),
    ]


def get_monthly_histories_from_db(
    web_account_id: int | typing.Sequence[int],
    year: int,
    month: int,
    session: sqlalchemy.orm.Session,
) -> list[dict[str, typing.Any]]:
    """DBから指定年月の受講履歴を取得し、UI表示用のリストに整形して返す。"""
    start_date = datetime.datetime(year, month, 1, 0, 0, 0)
    if month == 12:
        end_date = datetime.datetime(year + 1, 1, 1, 0, 0, 0)
    else:
        end_date = datetime.datetime(year, month + 1, 1, 0, 0, 0)

    ids = [web_account_id] if isinstance(web_account_id, int) else list(web_account_id)

    stmt = (
        sqlalchemy.select(model.LessonHistory)
        .options(
            sqlalchemy.orm.joinedload(model.LessonHistory.lesson).joinedload(
                model.Lesson.program
            ),
            sqlalchemy.orm.joinedload(model.LessonHistory.web_account),
        )
        .join(model.Lesson)
        .where(
            model.LessonHistory.web_account_id.in_(ids),
            model.Lesson.start_at >= start_date,
            model.Lesson.start_at < end_date,
            *get_valid_lesson_history_filters(),
        )
        .order_by(model.Lesson.start_at.asc())
    )
    histories = session.scalars(stmt).all()

    result: list[dict[str, typing.Any]] = []
    for h in histories:
        prog = h.lesson.program
        acc_icon = "🚴"
        if h.web_account and h.web_account.icon:
            acc_icon = h.web_account.icon
        instructor_name = h.lesson.instructor_name_1
        if h.lesson.instructor_name_2:
            instructor_name = (
                f"{h.lesson.instructor_name_1} / {h.lesson.instructor_name_2}"
            )
        result.append(
            {
                "アカウント": acc_icon,
                "受講日": h.lesson.start_at.strftime("%Y/%m/%d"),
                "開始時刻": h.lesson.start_at.strftime("%H:%M"),
                "終了時刻": h.lesson.end_at.strftime("%H:%M"),
                "プログラム": prog.name if prog else "",
                "インストラクター": instructor_name,
                "店舗": h.lesson.store_name,
                "バイク": h.bike_number,
                "チケット": h.ticket_type or "-",
                "状態": "キャンセル/欠席" if h.is_absent else "受講済",
                "_background_color": prog.background_color if prog else None,
                "_text_color": prog.text_color if prog else None,
            }
        )
    return result


def style_monthly_histories(
    histories: list[dict[str, typing.Any]],
) -> pandas.io.formats.style.Styler:
    """受講履歴のリストをpandas.DataFrameにし、プログラムセルの色をスタイル付けしたStylerを返す。"""
    df = pandas.DataFrame(histories)
    if df.empty:
        return df.style

    bg_colors = df.get("_background_color", [None] * len(df)).tolist()
    text_colors = df.get("_text_color", [None] * len(df)).tolist()
    display_df = df.drop(
        columns=["_background_color", "_text_color"],
        errors="ignore",
    )

    def style_program(col: pandas.Series) -> list[str]:
        return [
            f"background-color: {bg}; color: {txt};" if bg and txt else ""
            for bg, txt in zip(bg_colors, text_colors)
        ]

    return display_df.style.apply(style_program, subset=["プログラム"])


def get_monthly_summary(
    web_account_id: int | typing.Sequence[int],
    year: int,
    month: int,
    session: sqlalchemy.orm.Session,
    month_history: typing.Optional[feelpycle.api.MonthHistory] = None,
) -> dict[str, int]:
    """月間受講回数、累計受講回数、内訳サマリーを集計して返す。"""
    ids = [web_account_id] if isinstance(web_account_id, int) else list(web_account_id)

    # 累計受講数 (DB内)
    stmt_total = sqlalchemy.select(sqlalchemy.func.count(model.LessonHistory.id)).where(
        model.LessonHistory.web_account_id.in_(ids),
        model.LessonHistory.is_absent.is_(False),
        *get_valid_lesson_history_filters(),
    )
    db_total_count = session.scalar(stmt_total) or 0

    if month_history is not None and len(ids) <= 1:
        return {
            "total_count": month_history.summary_count or db_total_count,
            "monthly_count": month_history.member_count + month_history.ticket_count,
            "member_count": month_history.member_count,
            "ticket_count": month_history.ticket_count,
        }

    # APIレスポンスがない場合 (または複数アカウント集計時) はDBから当月分を集計
    start_date = datetime.datetime(year, month, 1, 0, 0, 0)
    if month == 12:
        end_date = datetime.datetime(year + 1, 1, 1, 0, 0, 0)
    else:
        end_date = datetime.datetime(year, month + 1, 1, 0, 0, 0)

    stmt_month = (
        sqlalchemy.select(model.LessonHistory)
        .join(model.Lesson)
        .where(
            model.LessonHistory.web_account_id.in_(ids),
            model.LessonHistory.is_absent.is_(False),
            model.Lesson.start_at >= start_date,
            model.Lesson.start_at < end_date,
            *get_valid_lesson_history_filters(),
        )
    )
    monthly_histories = session.scalars(stmt_month).all()

    member_count = 0
    ticket_count = 0
    for h in monthly_histories:
        ticket = h.ticket_type or ""
        if "マンスリー" in ticket:
            member_count += 1
        elif ticket:
            ticket_count += 1
        else:
            member_count += 1

    return {
        "total_count": db_total_count,
        "monthly_count": len(monthly_histories),
        "member_count": member_count,
        "ticket_count": ticket_count,
    }


def get_first_lesson_year_month(
    account: typing.Optional[feelpycle.api.Account],
    web_account_id: typing.Optional[int | typing.Sequence[int]],
    session: sqlalchemy.orm.Session,
) -> tuple[int, int]:
    """初回レッスン受講日の年月を取得する。

    APIまたはDBから初回受講日を取得し、その最小年月を返す。
    取得できない場合は現在年月を返す。
    """
    now = datetime.datetime.now()
    now_ym = (now.year, now.month)
    candidate_yms: list[tuple[int, int]] = []

    # 1. Feelcycle API から初回レッスン受講日を取得
    if account is not None:
        try:
            first_date = account.get_first_lesson_date()
            if hasattr(first_date, "year") and hasattr(first_date, "month"):
                candidate_yms.append((first_date.year, first_date.month))
        except Exception as e:
            LOGGER.info(f"Could not get first lesson date from API: {e}")

    # 2. DB から最古のレッスン受講日を取得
    if web_account_id is not None:
        ids = (
            [web_account_id]
            if isinstance(web_account_id, int)
            else list(web_account_id)
        )
        if ids:
            try:
                stmt = (
                    sqlalchemy.select(sqlalchemy.func.min(model.Lesson.start_at))
                    .join(
                        model.LessonHistory,
                        model.LessonHistory.lesson_sid == model.Lesson.sid,
                    )
                    .where(
                        model.LessonHistory.web_account_id.in_(ids),
                        model.LessonHistory.is_absent.is_(False),
                        *get_valid_lesson_history_filters(),
                    )
                )
                min_date = session.scalar(stmt)
                if hasattr(min_date, "year") and hasattr(min_date, "month"):
                    candidate_yms.append((min_date.year, min_date.month))
            except Exception as e:
                LOGGER.info(f"Could not get first lesson date from DB: {e}")

    if not candidate_yms:
        return now_ym

    return min(min(candidate_yms), now_ym)


def generate_period_options(
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
) -> list[str]:
    """集計期間の選択肢リストを生成する。

    「全期間」を先頭に、年単位(降順)とその年の年月(降順)を組み合わせたリストを返す。
    例: ["全期間", "2026年全体", "2026年10月", ..., "2026年1月", "2025年全体", ...]
    """
    if (start_year, start_month) > (end_year, end_month):
        start_year, start_month = end_year, end_month

    options: list[str] = ["全期間"]
    for y in range(end_year, start_year - 1, -1):
        options.append(f"{y}年全体")
        max_m = end_month if y == end_year else 12
        min_m = start_month if y == start_year else 1
        for m in range(max_m, min_m - 1, -1):
            options.append(f"{y}年{m}月")
    return options


def parse_period_option(
    option_str: str,
) -> tuple[typing.Optional[int], typing.Optional[int]]:
    """集計期間の選択肢文字列から (year, month) のタプルを返す。

    - "全期間" -> (None, None)
    - "YYYY年全体" -> (YYYY, None)
    - "YYYY年M月" -> (YYYY, M)
    """
    if option_str == "全期間":
        return None, None
    if option_str.endswith("年全体"):
        year_str = option_str.replace("年全体", "")
        return int(year_str), None
    if "年" in option_str and option_str.endswith("月"):
        parts = option_str.split("年")
        year = int(parts[0])
        month = int(parts[1].replace("月", ""))
        return year, month
    return None, None


def get_total_lesson_count(
    web_account_ids: list[int],
    session: sqlalchemy.orm.Session,
    year: typing.Optional[int] = None,
    month: typing.Optional[int] = None,
) -> int:
    """指定期間における有効なレッスン受講回数の合計を返す。"""
    stmt = (
        sqlalchemy.select(sqlalchemy.func.count(model.LessonHistory.id))
        .join(model.Lesson, model.LessonHistory.lesson_sid == model.Lesson.sid)
        .where(
            model.LessonHistory.web_account_id.in_(web_account_ids),
            model.LessonHistory.is_absent.is_(False),
            *get_valid_lesson_history_filters(),
        )
    )
    if year is not None and month is not None:
        start_date = datetime.datetime(year, month, 1, 0, 0, 0)
        if month == 12:
            end_date = datetime.datetime(year + 1, 1, 1, 0, 0, 0)
        else:
            end_date = datetime.datetime(year, month + 1, 1, 0, 0, 0)
        stmt = stmt.where(
            model.Lesson.start_at >= start_date,
            model.Lesson.start_at < end_date,
        )
    elif year is not None:
        start_date = datetime.datetime(year, 1, 1, 0, 0, 0)
        end_date = datetime.datetime(year + 1, 1, 1, 0, 0, 0)
        stmt = stmt.where(
            model.Lesson.start_at >= start_date,
            model.Lesson.start_at < end_date,
        )
    return session.scalar(stmt) or 0


def get_instructor_summary(
    web_account_ids: list[int],
    session: sqlalchemy.orm.Session,
    year: typing.Optional[int] = None,
    month: typing.Optional[int] = None,
    order_by_count: bool = False,
) -> list[dict[str, typing.Any]]:
    """インストラクター別の初回受講日と受講回数を集計して返す。

    ペアでのレッスンの場合は「メイン / サブ」として1つのペア枠(1回分)として集計する。
    year と month を指定するとその年月のレッスンのみを対象とし、
    year のみ指定するとその年のレッスン全体を対象とする。
    order_by_count が True の場合は受講回数の降順でソートする。
    """
    filters = [
        model.LessonHistory.web_account_id.in_(web_account_ids),
        model.LessonHistory.is_absent.is_(False),
        *get_valid_lesson_history_filters(),
    ]
    if year is not None and month is not None:
        start_date = datetime.datetime(year, month, 1, 0, 0, 0)
        if month == 12:
            end_date = datetime.datetime(year + 1, 1, 1, 0, 0, 0)
        else:
            end_date = datetime.datetime(year, month + 1, 1, 0, 0, 0)
        filters.extend(
            [
                model.Lesson.start_at >= start_date,
                model.Lesson.start_at < end_date,
            ]
        )
    elif year is not None:
        start_date = datetime.datetime(year, 1, 1, 0, 0, 0)
        end_date = datetime.datetime(year + 1, 1, 1, 0, 0, 0)
        filters.extend(
            [
                model.Lesson.start_at >= start_date,
                model.Lesson.start_at < end_date,
            ]
        )

    instructor_expr = sqlalchemy.case(
        (
            sqlalchemy.and_(
                model.Lesson.instructor_name_2.is_not(None),
                model.Lesson.instructor_name_2 != "",
            ),
            model.Lesson.instructor_name_1 + " / " + model.Lesson.instructor_name_2,
        ),
        else_=model.Lesson.instructor_name_1,
    ).label("instructor_name")

    stmt = (
        sqlalchemy.select(
            instructor_expr,
            sqlalchemy.func.min(model.Lesson.start_at).label("first_taken"),
            sqlalchemy.func.count(model.LessonHistory.id).label("count"),
        )
        .join(model.LessonHistory, model.LessonHistory.lesson_sid == model.Lesson.sid)
        .where(*filters)
        .group_by(instructor_expr)
    )
    if order_by_count:
        stmt = stmt.order_by(
            sqlalchemy.desc("count"),
            sqlalchemy.text("first_taken"),
        )
    else:
        stmt = stmt.order_by(sqlalchemy.text("first_taken"))

    rows = session.execute(stmt).all()
    return [
        {
            "Instructor": row.instructor_name,
            "First taken": row.first_taken.strftime("%Y/%m/%d")
            if row.first_taken
            else "",
            "count": row.count,
        }
        for row in rows
    ]


def get_program_summary(
    web_account_ids: list[int],
    session: sqlalchemy.orm.Session,
    year: typing.Optional[int] = None,
    month: typing.Optional[int] = None,
    order_by_count: bool = False,
) -> list[dict[str, typing.Any]]:
    """プログラム別の初回受講日と受講回数を集計して返す。

    戻り値の各dictには ``_background_color`` と ``_text_color`` を含む。
    year と month を指定するとその年月のレッスンのみを対象とし、
    year のみ指定するとその年のレッスン全体を対象とする。
    order_by_count が True の場合は受講回数の降順でソートする。
    """
    stmt = (
        sqlalchemy.select(
            model.Program.name.label("program_name"),
            model.Program.background_color,
            model.Program.text_color,
            sqlalchemy.func.min(model.Lesson.start_at).label("first_taken"),
            sqlalchemy.func.count(model.LessonHistory.id).label("count"),
        )
        .join(model.LessonHistory, model.LessonHistory.lesson_sid == model.Lesson.sid)
        .join(model.Program, model.Lesson.program_id == model.Program.id)
        .where(
            model.LessonHistory.web_account_id.in_(web_account_ids),
            model.LessonHistory.is_absent.is_(False),
            *get_valid_lesson_history_filters(),
        )
        .group_by(
            model.Program.name,
            model.Program.background_color,
            model.Program.text_color,
        )
    )
    if order_by_count:
        stmt = stmt.order_by(
            sqlalchemy.desc("count"),
            sqlalchemy.text("first_taken"),
        )
    else:
        stmt = stmt.order_by(sqlalchemy.text("first_taken"))

    if year is not None and month is not None:
        start_date = datetime.datetime(year, month, 1, 0, 0, 0)
        if month == 12:
            end_date = datetime.datetime(year + 1, 1, 1, 0, 0, 0)
        else:
            end_date = datetime.datetime(year, month + 1, 1, 0, 0, 0)
        stmt = stmt.where(
            model.Lesson.start_at >= start_date,
            model.Lesson.start_at < end_date,
        )
    elif year is not None:
        start_date = datetime.datetime(year, 1, 1, 0, 0, 0)
        end_date = datetime.datetime(year + 1, 1, 1, 0, 0, 0)
        stmt = stmt.where(
            model.Lesson.start_at >= start_date,
            model.Lesson.start_at < end_date,
        )
    rows = session.execute(stmt).all()
    return [
        {
            "Program": row.program_name,
            "First taken": row.first_taken.strftime("%Y/%m/%d")
            if row.first_taken
            else "",
            "count": row.count,
            "_background_color": row.background_color,
            "_text_color": row.text_color,
        }
        for row in rows
    ]


def get_studio_summary(
    web_account_ids: list[int],
    session: sqlalchemy.orm.Session,
    year: typing.Optional[int] = None,
    month: typing.Optional[int] = None,
) -> list[dict[str, typing.Any]]:
    """スタジオ別の初回受講日と受講回数を集計して返す。

    year と month を指定するとその年月のレッスンのみを対象とし、
    year のみ指定するとその年のレッスン全体を対象とする。
    """
    stmt = (
        sqlalchemy.select(
            model.Lesson.store_name,
            sqlalchemy.func.min(model.Lesson.start_at).label("first_visit"),
            sqlalchemy.func.count(model.LessonHistory.id).label("count"),
        )
        .join(model.LessonHistory, model.LessonHistory.lesson_sid == model.Lesson.sid)
        .where(
            model.LessonHistory.web_account_id.in_(web_account_ids),
            model.LessonHistory.is_absent.is_(False),
            *get_valid_lesson_history_filters(),
        )
        .group_by(model.Lesson.store_name)
        .order_by(sqlalchemy.text("first_visit"))
    )
    if year is not None and month is not None:
        start_date = datetime.datetime(year, month, 1, 0, 0, 0)
        if month == 12:
            end_date = datetime.datetime(year + 1, 1, 1, 0, 0, 0)
        else:
            end_date = datetime.datetime(year, month + 1, 1, 0, 0, 0)
        stmt = stmt.where(
            model.Lesson.start_at >= start_date,
            model.Lesson.start_at < end_date,
        )
    elif year is not None:
        start_date = datetime.datetime(year, 1, 1, 0, 0, 0)
        end_date = datetime.datetime(year + 1, 1, 1, 0, 0, 0)
        stmt = stmt.where(
            model.Lesson.start_at >= start_date,
            model.Lesson.start_at < end_date,
        )
    rows = session.execute(stmt).all()
    return [
        {
            "Studio": row.store_name,
            "First visit": row.first_visit.strftime("%Y/%m/%d")
            if row.first_visit
            else "",
            "count": row.count,
        }
        for row in rows
    ]
