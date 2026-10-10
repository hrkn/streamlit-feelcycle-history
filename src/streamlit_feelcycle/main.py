import base64
import datetime
import logging
import pathlib
import sys
import time

import feelpycle.api
import pandas
import sqlalchemy
import sqlalchemy.orm
import streamlit as st
import streamlit.runtime.scriptrunner
import streamlit_persist_session

import streamlit_feelcycle.database as database
import streamlit_feelcycle.history as history
import streamlit_feelcycle.model as model

# ページ設定
st.set_page_config(page_title="Feelcycle", layout="wide")

_BACKGROUND_CSS: str | None = None


def get_background_css() -> str:
    global _BACKGROUND_CSS
    if _BACKGROUND_CSS is not None:
        return _BACKGROUND_CSS

    logo_path = (
        pathlib.Path(__file__).resolve().parent / "assets" / "feelcycle-logo-3q.png"
    )
    if not logo_path.exists():
        _BACKGROUND_CSS = ""
        return _BACKGROUND_CSS

    with open(logo_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")

    _BACKGROUND_CSS = f"""
<style>
[data-testid="stAppViewContainer"] {{
    background-image: url("data:image/png;base64,{encoded}");
    background-repeat: no-repeat;
    background-attachment: fixed;
    background-position: right bottom;
}}
</style>
"""
    return _BACKGROUND_CSS


def set_background_logo() -> None:
    css = get_background_css()
    if css:
        st.markdown(css, unsafe_allow_html=True)


set_background_logo()


@streamlit_persist_session.persist("feelcycle-session")
class PersistedSession:
    def __init__(self):
        self.logged_in = False
        self.email = None
        self.name = None
        self.store = None
        self.plan = None
        self.member_id = None
        self.api_session_state = None

    def clear_cookie_state(self):
        self.__init__()


if "pytest" in sys.modules:

    class DummyPersistedSession:
        def __init__(self):
            self.logged_in = False
            self.email = None
            self.name = None
            self.store = None
            self.plan = None
            self.member_id = None
            self.api_session_state = None

        def clear_cookie_state(self):
            pass

    persisted = DummyPersistedSession()
else:
    persisted = PersistedSession()

# Cookie読み込み待ち（テスト時はスキップ）
if "pytest" not in sys.modules:
    if getattr(persisted, "_is_temp_placeholder", False):
        st.info("セッション情報を読み込んでいます...")
        st.stop()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d [%(levelname).4s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler()],
)
LOGGER = logging.getLogger(__name__)


# Streamlit UI Execution Guard
if streamlit.runtime.scriptrunner.get_script_run_ctx() is None:
    sys.exit(0)

# アプリ全体の起動時に一度だけ初期化を実行 (ページリロードでは実行されない)
database.initialize_app_once()

# セッション状態の初期化
if "logged_in" not in st.session_state:
    st.session_state.logged_in = persisted.logged_in
if "email" not in st.session_state:
    st.session_state.email = persisted.email
if "name" not in st.session_state:
    st.session_state.name = persisted.name
if "store" not in st.session_state:
    st.session_state.store = persisted.store
if "plan" not in st.session_state:
    st.session_state.plan = persisted.plan
if "member_id" not in st.session_state:
    st.session_state.member_id = getattr(persisted, "member_id", None)

# member_id / web_account_id の復元・解決
if st.session_state.logged_in and (
    st.session_state.get("member_id") is None
    or st.session_state.get("web_account_id") is None
):
    if st.session_state.get("email"):
        with sqlalchemy.orm.Session(database.local_engine) as session:
            stmt = sqlalchemy.select(model.WebAccount).where(
                model.WebAccount.email == st.session_state.email
            )
            wa = session.scalars(stmt).first()
            if wa:
                st.session_state.web_account_id = wa.id
                st.session_state.member_id = wa.member_id
                persisted.member_id = wa.member_id

# Feelcycle Account の初期化・復元
if "account" not in st.session_state:
    account = feelpycle.api.Account()
    if persisted.logged_in and persisted.api_session_state:
        account.set_session_state(persisted.api_session_state)
    st.session_state.account = account


@st.dialog("アカウント追加")
def show_add_account_dialog(target_member_id: int) -> None:
    st.write("連携するFeelcycleアカウントのログイン情報を入力してください。")

    # 既に同一会員が使用しているアイコンを取得して候補から除外
    with sqlalchemy.orm.Session(database.local_engine) as session:
        stmt = sqlalchemy.select(model.WebAccount.icon).where(
            model.WebAccount.member_id == target_member_id
        )
        used_icons = set(session.scalars(stmt).all())

    available_icons = [
        icon for icon in history.DEFAULT_ACCOUNT_ICONS if icon not in used_icons
    ]
    if not available_icons:
        available_icons = history.DEFAULT_ACCOUNT_ICONS

    with st.form("add_account_form"):
        new_email = st.text_input("メールアドレス")
        new_password = st.text_input("パスワード", type="password")
        selected_icon = st.selectbox(
            "アイコン",
            options=available_icons,
            index=0,
            filter_mode=None,
        )
        submit_add = st.form_submit_button("追加して履歴を同期")

    if submit_add:
        if not new_email or not new_password:
            st.error("メールアドレスとパスワードを入力してください。")
            return

        with sqlalchemy.orm.Session(database.local_engine) as session:
            stmt = sqlalchemy.select(model.WebAccount).where(
                model.WebAccount.email == new_email
            )
            existing_wa = session.scalars(stmt).first()
            if existing_wa:
                st.error("既に連携済みのアカウントです。")
                return

        add_account = feelpycle.api.Account()
        if add_account.login(id=new_email, password=new_password):
            with sqlalchemy.orm.Session(database.local_engine) as session:
                stmt = sqlalchemy.select(model.WebAccount).where(
                    model.WebAccount.email == new_email
                )
                existing_wa = session.scalars(stmt).first()
                if existing_wa:
                    st.error("既に連携済みのアカウントです。")
                    return

                new_wa = model.WebAccount(
                    email=new_email,
                    member_id=target_member_id,
                    icon=selected_icon,
                )
                session.add(new_wa)
                session.commit()
                target_wa_id = new_wa.id

                progress_bar = st.progress(0.0, text="受講履歴の更新準備中...")

                def update_progress(
                    current: int, total: int, year: int, month: int
                ) -> None:
                    ratio = min(1.0, max(0.0, current / total))
                    progress_bar.progress(
                        ratio,
                        text=f"受講履歴を更新中... ({current}/{total}か月: {year}年{month:02d}月)",
                    )

                sync_result = history.sync_all_histories(
                    add_account,
                    target_wa_id,
                    session,
                    on_progress=update_progress,
                )
                progress_bar.empty()

            if sync_result["updated"] > 0:
                st.success(
                    f"アカウントを追加しました。{sync_result['updated']}か月分の履歴を更新しました。"
                )
            else:
                st.success("アカウントを追加しました。")

            st.session_state.first_lesson_year = None
            time.sleep(1.0)
            st.rerun()
        else:
            st.error(
                "ログインに失敗しました。メールアドレスまたはパスワードが正しくありません。"
            )


@st.dialog("アカウント連携解除")
def show_unlink_account_dialog(web_account_id: int, email: str) -> None:
    st.write(f"**{email}** の連携を解除しますか？")
    st.caption("解除すると、このアカウントに関連する受講履歴データも削除されます。")

    current_member_id = st.session_state.get("member_id")
    with sqlalchemy.orm.Session(database.local_engine) as session:
        stmt = sqlalchemy.select(model.WebAccount).where(
            model.WebAccount.member_id == current_member_id
        )
        linked_count = len(session.scalars(stmt).all())

    if linked_count <= 1:
        st.error("連携アカウントが1つのため解除できません。")
        return

    if email == st.session_state.get("email"):
        st.error("ログイン中のアカウントは解除できません。")
        return

    col_confirm, col_cancel = st.columns([1, 1])
    with col_confirm:
        if st.button(
            "解除する", type="primary", key=f"confirm_unlink_{web_account_id}"
        ):
            with sqlalchemy.orm.Session(database.local_engine) as session:
                history.unlink_web_account(web_account_id, session)
            st.session_state.first_lesson_year = None
            st.success("連携を解除しました。")
            time.sleep(0.5)
            st.rerun()
    with col_cancel:
        if st.button("キャンセル", key=f"cancel_unlink_{web_account_id}"):
            st.rerun()


@st.dialog("アイコン変更")
def show_edit_icon_dialog(web_account_id: int, email: str, current_icon: str) -> None:
    st.write(f"**{email}** のアイコンを変更します。")

    # 他の自分のアカウントで使用中のアイコンを除外
    current_member_id = st.session_state.get("member_id")
    used_by_others: set[str] = set()
    if current_member_id:
        with sqlalchemy.orm.Session(database.local_engine) as session:
            stmt = sqlalchemy.select(model.WebAccount.icon).where(
                model.WebAccount.member_id == current_member_id,
                model.WebAccount.id != web_account_id,
            )
            used_by_others = set(session.scalars(stmt).all())

    available_icons = [
        icon for icon in history.DEFAULT_ACCOUNT_ICONS if icon not in used_by_others
    ]
    if not available_icons:
        available_icons = history.DEFAULT_ACCOUNT_ICONS

    current_index = 0
    if current_icon in available_icons:
        current_index = available_icons.index(current_icon)

    selected_icon = st.selectbox(
        "アイコン",
        options=available_icons,
        index=current_index,
        key=f"edit_icon_select_{web_account_id}",
        filter_mode=None,
    )
    if st.button("変更を保存", key=f"save_icon_btn_{web_account_id}"):
        with sqlalchemy.orm.Session(database.local_engine) as session:
            stmt = sqlalchemy.select(model.WebAccount).where(
                model.WebAccount.id == web_account_id
            )
            target_wa = session.scalars(stmt).first()
            if target_wa:
                target_wa.icon = selected_icon
                session.commit()
        st.success("アイコンを変更しました。")
        time.sleep(0.5)
        st.rerun()


# サイドバーにログイン状態を表示
with st.sidebar:
    st.subheader("ログイン状態")
    if st.session_state.logged_in:
        st.write(f"ログイン中: {st.session_state.name}")
        if st.session_state.store and st.session_state.plan:
            st.caption(f"{', '.join(st.session_state.store)} / {st.session_state.plan}")

        # 連携アカウント一覧の表示
        current_member_id = st.session_state.get("member_id")
        if current_member_id:
            with sqlalchemy.orm.Session(database.local_engine) as session:
                stmt = (
                    sqlalchemy.select(model.WebAccount)
                    .where(model.WebAccount.member_id == current_member_id)
                    .order_by(model.WebAccount.id.asc())
                )
                linked_accounts = session.scalars(stmt).all()

            st.markdown("---")
            st.subheader("連携アカウント")
            for wa in linked_accounts:
                icon_str = wa.icon if wa.icon else "🚴"
                is_current_login = wa.email == st.session_state.email
                badge = " (ログイン中)" if is_current_login else ""
                col_info, col_edit, col_del = st.columns([3, 1, 1])
                with col_info:
                    st.write(f"{icon_str} **{wa.email}**{badge}")
                with col_edit:
                    if st.button(
                        "✏️",
                        key=f"edit_icon_btn_{wa.id}",
                        help="アイコンを変更",
                    ):
                        show_edit_icon_dialog(wa.id, wa.email, wa.icon)
                with col_del:
                    can_unlink = len(linked_accounts) > 1 and not is_current_login
                    if is_current_login:
                        unlink_help = "ログイン中のため解除できません"
                    elif len(linked_accounts) <= 1:
                        unlink_help = "連携アカウントが1つのため解除できません"
                    else:
                        unlink_help = "連携を解除"

                    if st.button(
                        "🗑️",
                        key=f"unlink_btn_{wa.id}",
                        disabled=not can_unlink,
                        help=unlink_help,
                    ):
                        show_unlink_account_dialog(wa.id, wa.email)

            if st.button("➕ アカウント追加"):
                show_add_account_dialog(current_member_id)

        if st.button("ログアウト"):
            st.session_state.logged_in = False
            st.session_state.email = None
            st.session_state.name = None
            st.session_state.store = None
            st.session_state.plan = None
            st.session_state.member_id = None
            st.session_state.web_account_id = None
            st.session_state.first_lesson_year = None
            if "account" in st.session_state:
                st.session_state.account.logout()

            # 永続化情報のクリア
            persisted.clear_cookie_state()

            time.sleep(0.5)
            st.rerun()
    else:
        st.write("未ログイン")

# 以降メインフレーム描画
st.title("Feelcycle")

# 未ログイン時
if not st.session_state.logged_in:
    st.subheader("ログイン")
    with st.form("login_form"):
        email_input = st.text_input("メールアドレス")
        password_input = st.text_input("パスワード", type="password")
        submit_button = st.form_submit_button("ログイン")

        if submit_button:
            if not email_input or not password_input:
                st.error("メールアドレスとパスワードを入力してください。")
            else:
                account = st.session_state.account
                if account.login(id=email_input, password=password_input):
                    # mypage から名前、店舗情報、プラン情報を取得
                    mypage_info = account.mypage()
                    member_name = mypage_info.member_name
                    store_list = mypage_info.store
                    member_plan = mypage_info.member_type

                    # データベースに登録があるかチェック
                    with sqlalchemy.orm.Session(database.local_engine) as session:
                        stmt = (
                            sqlalchemy.select(model.WebAccount)
                            .options(sqlalchemy.orm.joinedload(model.WebAccount.member))
                            .where(model.WebAccount.email == email_input)
                        )
                        web_account = session.scalars(stmt).first()

                        if not web_account:
                            member = model.Member(name=member_name)
                            session.add(member)
                            session.flush()  # idを発行

                            web_account = model.WebAccount(
                                email=email_input,
                                member_id=member.id,
                                icon="🚴",
                            )
                            session.add(web_account)
                            session.commit()
                            current_name = member_name
                        else:
                            current_name = web_account.member.name
                        web_account_id = web_account.id
                        member_id = web_account.member_id

                    st.session_state.logged_in = True
                    st.session_state.email = email_input
                    st.session_state.name = current_name
                    st.session_state.store = store_list
                    st.session_state.plan = member_plan
                    st.session_state.web_account_id = web_account_id
                    st.session_state.member_id = member_id

                    # 永続化処理を行う
                    persisted.logged_in = True
                    persisted.email = email_input
                    persisted.name = current_name
                    persisted.store = store_list
                    persisted.plan = member_plan
                    persisted.member_id = member_id
                    persisted.api_session_state = account.get_session_state()

                    # ログイン直後に受講履歴を自動更新
                    progress_bar = st.progress(0.0, text="受講履歴の更新準備中...")

                    def update_progress(
                        current: int, total: int, year: int, month: int
                    ) -> None:
                        ratio = min(1.0, max(0.0, current / total))
                        progress_bar.progress(
                            ratio,
                            text=f"受講履歴を更新中... ({current}/{total}か月: {year}年{month:02d}月)",
                        )

                    with sqlalchemy.orm.Session(database.local_engine) as session:
                        sync_result = history.sync_all_histories(
                            account,
                            web_account_id,
                            session,
                            on_progress=update_progress,
                        )
                    progress_bar.empty()
                    if sync_result["updated"] > 0:
                        st.success(
                            f"ログインに成功しました。{sync_result['updated']}か月分の履歴を更新しました。"
                        )
                    else:
                        st.success("ログインに成功しました。")

                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(
                        "ログインに失敗しました。メールアドレスまたはパスワードが正しくありません。"
                    )

# ログイン成功後
else:
    # member_id / web_account_id の確認・解決
    if (
        st.session_state.get("member_id") is None
        or st.session_state.get("web_account_id") is None
    ) and st.session_state.email:
        with sqlalchemy.orm.Session(database.local_engine) as session:
            stmt = sqlalchemy.select(model.WebAccount).where(
                model.WebAccount.email == st.session_state.email
            )
            wa = session.scalars(stmt).first()
            if wa:
                st.session_state.web_account_id = wa.id
                st.session_state.member_id = wa.member_id
                persisted.member_id = wa.member_id

    # 会員に紐づくすべてのWebアカウントIDを取得
    member_id = st.session_state.get("member_id")
    web_account_ids: list[int] = []
    if member_id:
        with sqlalchemy.orm.Session(database.local_engine) as session:
            stmt = (
                sqlalchemy.select(model.WebAccount.id)
                .where(model.WebAccount.member_id == member_id)
                .order_by(model.WebAccount.id.asc())
            )
            web_account_ids = list(session.scalars(stmt).all())
    elif st.session_state.get("web_account_id"):
        web_account_ids = [st.session_state.web_account_id]

    # 初回受講年月の取得(セッション未保持の場合)
    if (
        "first_lesson_ym" not in st.session_state
        or st.session_state.first_lesson_ym is None
    ):
        with sqlalchemy.orm.Session(database.local_engine) as session:
            first_year, first_month = history.get_first_lesson_year_month(
                account=st.session_state.get("account"),
                web_account_id=web_account_ids,
                session=session,
            )
            st.session_state.first_lesson_ym = (first_year, first_month)

    now = datetime.datetime.now()
    first_ym = st.session_state.first_lesson_ym or (now.year, now.month)
    start_ym = feelpycle.api.YearMonth(*first_ym)
    end_ym = feelpycle.api.YearMonth(now.year, now.month)
    year_month_options = [
        f"{y}年{m}月"
        for y, m in (
            ym.year_month()
            for ym in reversed(list(feelpycle.api.YearMonth.range(start_ym, end_ym)))
        )
    ]
    if not year_month_options:
        year_month_options = [f"{now.year}年{now.month}月"]

    # 集計期間選択肢 (全期間 + 年全体 + 各年月降順)
    start_year, start_month = first_ym
    statistics_period_options = history.generate_period_options(
        start_year, start_month, now.year, now.month
    )

    tab_history, tab_instructor, tab_program, tab_studio, tab_statistics = st.tabs(
        ["History", "Instructor", "Program", "Studio", "Statistics"]
    )

    @st.fragment
    def render_history_tab() -> None:
        st.subheader("受講履歴")

        col_ym, _ = st.columns([2, 2])
        with col_ym:
            selected_ym = st.selectbox(
                "年月",
                options=year_month_options,
                index=0,
                key="history_selected_year_month",
                filter_mode=None,
            )

        selected_year = int(selected_ym.split("年")[0])
        selected_month = int(selected_ym.split("年")[1].replace("月", ""))

        if web_account_ids:
            # DBから指定年月の履歴とサマリーを取得 (会員に紐づく全Webアカウント分)
            with sqlalchemy.orm.Session(database.local_engine) as session:
                histories = history.get_monthly_histories_from_db(
                    web_account_ids, selected_year, selected_month, session
                )
                summary = history.get_monthly_summary(
                    web_account_ids,
                    selected_year,
                    selected_month,
                    session,
                )

            # サマリー指標を表示
            st.markdown("---")
            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            m_col1.metric("当月受講回数", f"{summary['monthly_count']} 回")
            m_col2.metric("マンスリー受講", f"{summary['member_count']} 回")
            m_col3.metric("チケット受講", f"{summary['ticket_count']} 回")
            m_col4.metric("累計受講回数", f"{summary['total_count']} 回")

            st.markdown("---")

            # 受講履歴一覧テーブル
            if histories:
                styled_df = history.style_monthly_histories(histories)
                st.dataframe(styled_df, width="stretch", hide_index=True)
            else:
                st.info(f"{selected_year}年{selected_month}月の受講履歴はありません。")

    @st.fragment
    def render_statistics_tab() -> None:
        st.subheader("集計")

        col_period, _ = st.columns([2, 2])
        with col_period:
            selected_period = st.selectbox(
                "集計期間",
                options=statistics_period_options,
                index=0,
                key="statistics_selected_period",
                filter_mode=None,
            )

        filter_year, filter_month = history.parse_period_option(selected_period)

        total_count = 0
        if web_account_ids:
            with sqlalchemy.orm.Session(database.local_engine) as session:
                total_count = history.get_total_lesson_count(
                    web_account_ids, session, year=filter_year, month=filter_month
                )

        st.markdown(f"### Total: {total_count}")

        col_program, col_instructor = st.columns(2)

        with col_program:
            st.markdown("##### 受講プログラム")
            if web_account_ids:
                with sqlalchemy.orm.Session(database.local_engine) as session:
                    prog_data = history.get_program_summary(
                        web_account_ids,
                        session,
                        year=filter_year,
                        month=filter_month,
                        order_by_count=True,
                    )
                if prog_data:
                    df_prog = pandas.DataFrame(prog_data)
                    bg_colors = df_prog["_background_color"].tolist()
                    text_colors = df_prog["_text_color"].tolist()
                    display_prog_df = df_prog[["Program", "count"]]

                    def style_program(col: pandas.Series) -> list[str]:
                        return [
                            f"background-color: {bg}; color: {txt};"
                            if bg and txt
                            else ""
                            for bg, txt in zip(bg_colors, text_colors)
                        ]

                    styled_prog = display_prog_df.style.apply(
                        style_program, subset=["Program"]
                    )
                    st.dataframe(
                        styled_prog,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Program": st.column_config.TextColumn("受講プログラム名"),
                            "count": st.column_config.NumberColumn("回数"),
                        },
                    )
                else:
                    st.info("受講履歴がありません。")

        with col_instructor:
            st.markdown("##### インストラクター")
            if web_account_ids:
                with sqlalchemy.orm.Session(database.local_engine) as session:
                    inst_data = history.get_instructor_summary(
                        web_account_ids,
                        session,
                        year=filter_year,
                        month=filter_month,
                        order_by_count=True,
                    )
                if inst_data:
                    df_inst = pandas.DataFrame(inst_data)
                    display_inst_df = df_inst[["Instructor", "count"]]
                    st.dataframe(
                        display_inst_df,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Instructor": st.column_config.TextColumn(
                                "インストラクター"
                            ),
                            "count": st.column_config.NumberColumn("回数"),
                        },
                    )
                else:
                    st.info("受講履歴がありません。")

    @st.fragment
    def render_instructor_tab() -> None:
        st.subheader("インストラクター別一覧")

        if web_account_ids:
            with sqlalchemy.orm.Session(database.local_engine) as session:
                data = history.get_instructor_summary(web_account_ids, session)
            if data:
                df = pandas.DataFrame(data)
                st.dataframe(
                    df,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Instructor": st.column_config.TextColumn("Instructor"),
                        "First taken": st.column_config.TextColumn("First taken"),
                        "count": st.column_config.NumberColumn("count"),
                    },
                )
            else:
                st.info("受講履歴がありません。")

    @st.fragment
    def render_program_tab() -> None:
        st.subheader("プログラム別一覧")

        if web_account_ids:
            with sqlalchemy.orm.Session(database.local_engine) as session:
                data = history.get_program_summary(web_account_ids, session)
            if data:
                df = pandas.DataFrame(data)
                bg_colors = df["_background_color"].tolist()
                text_colors = df["_text_color"].tolist()
                display_df = df.drop(
                    columns=["_background_color", "_text_color"], errors="ignore"
                )

                def style_program(col: pandas.Series) -> list[str]:
                    return [
                        f"background-color: {bg}; color: {txt};" if bg and txt else ""
                        for bg, txt in zip(bg_colors, text_colors)
                    ]

                styled = display_df.style.apply(style_program, subset=["Program"])
                st.dataframe(
                    styled,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Program": st.column_config.TextColumn("Program"),
                        "First taken": st.column_config.TextColumn("First taken"),
                        "count": st.column_config.NumberColumn("count"),
                    },
                )
            else:
                st.info("受講履歴がありません。")

    @st.fragment
    def render_studio_tab() -> None:
        st.subheader("スタジオ別一覧")

        if web_account_ids:
            with sqlalchemy.orm.Session(database.local_engine) as session:
                data = history.get_studio_summary(web_account_ids, session)
            if data:
                df = pandas.DataFrame(data)
                st.dataframe(
                    df,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Studio": st.column_config.TextColumn("Studio"),
                        "First visit": st.column_config.TextColumn("First visit"),
                        "count": st.column_config.NumberColumn("count"),
                    },
                )
            else:
                st.info("受講履歴がありません。")

    with tab_history:
        render_history_tab()
    with tab_instructor:
        render_instructor_tab()
    with tab_program:
        render_program_tab()
    with tab_studio:
        render_studio_tab()
    with tab_statistics:
        render_statistics_tab()
