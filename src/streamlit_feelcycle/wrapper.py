import datetime
import functools

import feelpycle_proxy as feelpycle

ACCOUNT = feelpycle.api.Account()

ACCOUNT._update_crsf_token_from_remote()


@functools.lru_cache(maxsize=50)
def get_lesson_calendar(
    target_date: datetime.date, store_id: int
) -> feelpycle.api.LessonCalendar:
    return ACCOUNT.get_lesson_calendar_by_store_nocache(
        starting_date=target_date, store_id=store_id
    )
