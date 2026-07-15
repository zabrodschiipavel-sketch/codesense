"""Хранилище: банк сниппетов и прогресс игрока. Обычные JSON-файлы, читаемые глазами."""

import json
import pathlib
import threading
from datetime import datetime, timezone

import srs

DATA_DIR = pathlib.Path(__file__).parent / "data"
SNIPPETS_FILE = DATA_DIR / "snippets.json"
PROGRESS_FILE = DATA_DIR / "progress.json"
CARDS_FILE = DATA_DIR / "cards.json"

_lock = threading.Lock()

RANKS = [
    (0, "Новичок"),
    (400, "Читатель"),
    (1200, "Толмач"),
    (2800, "Полиглот"),
    (5500, "Дешифровщик"),
    (10000, "Оракул"),
]

RECENT_LANGUAGES_WINDOW = 8
RECENT_THEMES_WINDOW = 12


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read(path: pathlib.Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write(path: pathlib.Path, payload) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_snippets() -> dict:
    return _read(SNIPPETS_FILE, {})


def get_snippet(snippet_id: str) -> dict | None:
    return load_snippets().get(snippet_id)


def save_snippet(snippet: dict) -> None:
    with _lock:
        snippets = load_snippets()
        snippets[snippet["id"]] = snippet
        _write(SNIPPETS_FILE, snippets)


def load_progress() -> dict:
    return _read(PROGRESS_FILE, {"rounds": [], "total_points": 0, "best_streak": 0})


def seen_snippet_ids() -> set[str]:
    return {r["snippet_id"] for r in load_progress()["rounds"]}


def unseen_snippets(difficulty: str | None = None) -> list[dict]:
    seen = seen_snippet_ids()
    out = []
    for snippet in load_snippets().values():
        if snippet["id"] in seen:
            continue
        if difficulty and snippet["difficulty"] != difficulty:
            continue
        out.append(snippet)
    return out


def recent_languages() -> list[str]:
    rounds = load_progress()["rounds"]
    return [r["language"] for r in rounds[-RECENT_LANGUAGES_WINDOW:]]


def recent_themes() -> list[str]:
    """Недавно выпадавшие темы — по всем языкам, а не по одному: модель липнет к
    подсчёту слов на любом языке, так что отсекать повторы надо глобально."""
    snippets = sorted(load_snippets().values(), key=lambda s: s.get("created_at", ""))
    themes = [s["theme"] for s in snippets if s.get("theme")]
    return themes[-RECENT_THEMES_WINDOW:]


def record_round(round_data: dict) -> dict:
    """Дописывает раунд в прогресс и возвращает обновлённую статистику."""
    with _lock:
        progress = load_progress()
        rounds = progress["rounds"]

        streak = 0
        for prev in reversed(rounds):
            if prev["percent"] >= 70:
                streak += 1
            else:
                break
        streak = streak + 1 if round_data["percent"] >= 70 else 0

        round_data["streak_after"] = streak
        round_data["at"] = now_iso()
        rounds.append(round_data)

        progress["total_points"] = sum(r["points"] for r in rounds)
        progress["best_streak"] = max(progress.get("best_streak", 0), streak)
        _write(PROGRESS_FILE, progress)
        return progress


def load_cards() -> dict:
    return _read(CARDS_FILE, {})


def get_card(card_id: str) -> dict | None:
    return load_cards().get(card_id)


def save_cards(new_cards: list[dict]) -> int:
    """Дописывает карточки, пропуская дубли по (язык, лицевая сторона). Возвращает число добавленных."""
    if not new_cards:
        return 0
    with _lock:
        cards = load_cards()
        seen = {(c["language"], c["front"].strip().lower()) for c in cards.values()}
        added = 0
        for card in new_cards:
            key = (card["language"], card["front"].strip().lower())
            if key in seen:
                continue
            seen.add(key)
            cards[card["id"]] = card
            added += 1
        if added:
            _write(CARDS_FILE, cards)
        return added


def update_card(card_id: str, state: dict) -> dict:
    with _lock:
        cards = load_cards()
        card = cards[card_id]
        card.update(state)
        _write(CARDS_FILE, cards)
        return card


def card_stats() -> dict:
    cards = list(load_cards().values())
    due = [c for c in cards if srs.is_due(c)]

    # Счётчик due по языкам нужен фильтру: он показывает, куда вообще есть смысл переключаться.
    by_language: dict[str, dict] = {}
    for c in cards:
        entry = by_language.setdefault(c["language"], {"cards": 0, "due": 0})
        entry["cards"] += 1
        if srs.is_due(c):
            entry["due"] += 1

    return {
        "total": len(cards),
        "due": len(due),
        "new": len([c for c in cards if c["reps"] == 0]),
        "learned": len([c for c in cards if c["reps"] >= 2]),
        "languages": len(by_language),
        "by_language": sorted(
            (
                {"language": k, "cards": v["cards"], "due": v["due"]}
                for k, v in by_language.items()
            ),
            key=lambda x: (-x["due"], -x["cards"], x["language"]),
        ),
    }


def rank_for(points: int) -> tuple[str, int | None, str | None]:
    """Возвращает (текущий ранг, порог следующего или None, название следующего или None)."""
    current = RANKS[0][1]
    for threshold, name in RANKS:
        if points >= threshold:
            current = name
        else:
            return current, threshold, name
    return current, None, None


def stats() -> dict:
    progress = load_progress()
    rounds = progress["rounds"]
    points = progress["total_points"]
    rank, next_at, next_rank = rank_for(points)

    by_language: dict[str, dict] = {}
    for r in rounds:
        entry = by_language.setdefault(r["language"], {"rounds": 0, "sum_percent": 0})
        entry["rounds"] += 1
        entry["sum_percent"] += r["percent"]
    languages = [
        {
            "language": lang,
            "rounds": e["rounds"],
            "avg_percent": round(e["sum_percent"] / e["rounds"]),
        }
        for lang, e in by_language.items()
    ]
    languages.sort(key=lambda x: (-x["rounds"], x["language"]))

    last10 = rounds[-10:]
    current_streak = rounds[-1]["streak_after"] if rounds else 0

    rank_floor = max(t for t, _ in RANKS if points >= t)
    if next_at is None:
        rank_progress = 1.0
    else:
        rank_progress = (points - rank_floor) / (next_at - rank_floor)

    return {
        "total_points": points,
        "rank": rank,
        "next_rank": next_rank,
        "next_rank_at": next_at,
        "rank_progress": round(rank_progress, 3),
        "rounds_played": len(rounds),
        "languages_seen": len(by_language),
        "avg_percent_all": round(sum(r["percent"] for r in rounds) / len(rounds)) if rounds else 0,
        "avg_percent_last10": round(sum(r["percent"] for r in last10) / len(last10)) if last10 else 0,
        "current_streak": current_streak,
        "best_streak": progress.get("best_streak", 0),
        "by_language": languages,
        "recent": [
            {
                "language": r["language"],
                "difficulty": r["difficulty"],
                "percent": r["percent"],
                "points": r["points"],
                "hints_used": r["hints_used"],
                "at": r["at"],
            }
            for r in rounds[-15:][::-1]
        ],
    }
