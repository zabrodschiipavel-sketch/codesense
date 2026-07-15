"""Интервальное повторение — SM-2 в варианте, близком к Anki.

Классический SM-2 пересчитывает лёгкость по формуле EF += 0.1 - (5-q)*(0.08 + (5-q)*0.02),
которая на «забыл» роняет её сразу на 0.8. Здесь взяты дельты Anki: они мягче и обкатаны
на миллионах карточек, а карточка, забытая пару раз, не проваливается в минимум навсегда.
"""

from datetime import datetime, timedelta, timezone

EASE_START = 2.5
EASE_MIN = 1.3
MAX_INTERVAL_DAYS = 365

# Дельты лёгкости и множители интервала на каждую кнопку.
RATINGS = {
    "again": {"ease_delta": -0.20, "label": "Забыл"},
    "hard": {"ease_delta": -0.15, "label": "Трудно"},
    "good": {"ease_delta": 0.0, "label": "Хорошо"},
    "easy": {"ease_delta": +0.15, "label": "Легко"},
}

FIRST_INTERVAL = 1  # дней после первого успешного вспоминания
SECOND_INTERVAL = 6  # дней после второго
EASY_FIRST = 4  # «легко» на новой карточке сразу отправляет её дальше, чем «хорошо»
HARD_MULT = 1.2
EASY_BONUS = 1.3


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_state() -> dict:
    """Свежая карточка: должна показаться сразу."""
    return {
        "ease": EASE_START,
        "interval": 0,
        "reps": 0,
        "lapses": 0,
        "due": now().isoformat(timespec="seconds"),
        "last_review": None,
    }


def _next_interval(state: dict, rating: str) -> int:
    """Новый интервал в днях. 0 означает «показать снова в этой же сессии»."""
    if rating == "again":
        return 0
    reps, interval, ease = state["reps"], state["interval"], state["ease"]

    if reps == 0:
        days = EASY_FIRST if rating == "easy" else FIRST_INTERVAL
    elif rating == "hard":
        # На коротких интервалах ×1.2 съедается округлением (1 * 1.2 -> 1), и карточка
        # навсегда застревает на одном дне. Поэтому шаг минимум в сутки.
        days = max(interval + 1, interval * HARD_MULT)
    elif reps == 1:
        days = SECOND_INTERVAL * (EASY_BONUS if rating == "easy" else 1)
    else:
        days = interval * ease * (EASY_BONUS if rating == "easy" else 1)

    return min(MAX_INTERVAL_DAYS, max(1, round(days)))


def apply_review(state: dict, rating: str) -> dict:
    """Возвращает новое состояние карточки после нажатия кнопки."""
    if rating not in RATINGS:
        raise ValueError(f"Неизвестная оценка: {rating}")

    interval = _next_interval(state, rating)
    ease = max(EASE_MIN, state["ease"] + RATINGS[rating]["ease_delta"])

    if rating == "again":
        reps = 0
        lapses = state["lapses"] + 1
    else:
        reps = state["reps"] + 1
        lapses = state["lapses"]

    moment = now()
    return {
        "ease": round(ease, 3),
        "interval": interval,
        "reps": reps,
        "lapses": lapses,
        # interval=0 -> due прямо сейчас, карточка вернётся в конец очереди сессии
        "due": (moment + timedelta(days=interval)).isoformat(timespec="seconds"),
        "last_review": moment.isoformat(timespec="seconds"),
    }


def preview_intervals(state: dict) -> dict:
    """Что будет с интервалом по каждой кнопке — рисуется прямо на кнопках."""
    out = {}
    for rating in RATINGS:
        days = _next_interval(state, rating)
        out[rating] = "сейчас" if days == 0 else _humanize(days)
    return out


def _humanize(days: int) -> str:
    if days < 30:
        return f"{days} дн"
    if days < 365:
        return f"{round(days / 30)} мес"
    return f"{days / 365:.1f} г"


def is_due(card: dict, at: datetime | None = None) -> bool:
    return datetime.fromisoformat(card["due"]) <= (at or now())


# Выбор из вариантов даёт только «попал / не попал». Если сводить это к again/good, лёгкость
# перестаёт двигаться вообще (у good дельта нулевая) и SM-2 вырождается в Лейтнера. Поэтому
# вторым сигналом берём время на ответ: скорость узнавания — доступный здесь прокси беглости.
FAST_SECONDS = 6
SLOW_SECONDS = 20


def rating_for_answer(correct: bool, seconds: float) -> str:
    if not correct:
        return "again"
    if seconds <= FAST_SECONDS:
        return "easy"
    if seconds <= SLOW_SECONDS:
        return "good"
    return "hard"
