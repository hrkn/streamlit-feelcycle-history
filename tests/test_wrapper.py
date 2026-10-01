import datetime
import unittest.mock

import streamlit_feelcycle.wrapper as wrapper


def test_get_lesson_calendar() -> None:
    # lru_cache のキャッシュをクリア
    wrapper.get_lesson_calendar.cache_clear()

    mock_calendar = unittest.mock.MagicMock()
    target_date = datetime.date(2026, 9, 1)
    store_id = 1

    with unittest.mock.patch.object(
        wrapper.ACCOUNT,
        "get_lesson_calendar_by_store_nocache",
        return_value=mock_calendar,
    ) as mock_method:
        # 初回呼び出し
        res1 = wrapper.get_lesson_calendar(target_date, store_id)
        assert res1 == mock_calendar
        mock_method.assert_called_once_with(
            starting_date=target_date, store_id=store_id
        )

        # 2回目呼び出し (lru_cache により再実行されないこと)
        res2 = wrapper.get_lesson_calendar(target_date, store_id)
        assert res2 == mock_calendar
        mock_method.assert_called_once()
