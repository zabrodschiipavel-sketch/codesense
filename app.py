"""CodeSense — тренажёр насмотренности: читаешь чужой код на случайном языке и объясняешь словами."""

import pathlib
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import deepseek
import languages
import srs
import storage

STATIC_DIR = pathlib.Path(__file__).parent / "static"

HINT_PENALTY = 0.10  # за каждую открытую подсказку, максимум -30%
PASS_PERCENT = 70  # порог, с которого раунд идёт в серию

app = FastAPI(title="CodeSense")

# Раунды в памяти: сервер должен знать, сколько подсказок открыто, до того как примет ответ.
# Перезапуск сервера теряет незавершённый раунд — сами сниппеты при этом остаются в банке.
ACTIVE: dict[str, dict] = {}


class NewRound(BaseModel):
    difficulty: str = "random"


class HintRequest(BaseModel):
    index: int = Field(ge=0, le=2)


class AnswerRequest(BaseModel):
    answer: str


class ReviewRequest(BaseModel):
    rating: str


class DeckRequest(BaseModel):
    language: str
    count: int = Field(default=20, ge=5, le=40)


def _full_stats() -> dict:
    """Всё, что рисует шапка. Раунд заводит карточки, поэтому их счётчик обязан
    ехать в том же ответе — иначе плашка «Карточки» оживёт только после перезагрузки."""
    return {**storage.stats(), "cards": storage.card_stats()}


def _build_cards(raw: list[dict], language: str, source: str, snippet_id: str | None) -> list[dict]:
    return [
        {
            "id": uuid.uuid4().hex[:12],
            "language": language,
            "front": c["front"],
            "back": c["back"],
            "kind": c["kind"],
            "source": source,
            "source_snippet_id": snippet_id,
            "created_at": storage.now_iso(),
            **srs.new_state(),
        }
        for c in raw
    ]


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/round")
async def new_round(req: NewRound):
    difficulty = languages.pick_difficulty(req.difficulty)
    language = languages.pick_language(difficulty, exclude=storage.recent_languages())
    theme = languages.pick_theme(exclude=storage.recent_themes())

    try:
        generated = await deepseek.generate_snippet(
            language=language,
            difficulty=difficulty,
            brief=languages.DIFFICULTY_BRIEF[difficulty],
            theme=theme,
        )
        snippet = {
            "id": uuid.uuid4().hex[:12],
            "language": language,
            "difficulty": difficulty,
            "theme": theme,
            "created_at": storage.now_iso(),
            **generated,
        }
        storage.save_snippet(snippet)
        source = "generated"
    except deepseek.DeepSeekError as exc:
        # API недоступен — отдаём непройденный сниппет из банка, чтобы тренировка не вставала.
        fallback = storage.unseen_snippets(difficulty) or storage.unseen_snippets()
        if not fallback:
            raise HTTPException(status_code=503, detail=str(exc))
        snippet = fallback[0]
        source = "cache"

    ACTIVE[snippet["id"]] = {"hints_used": 0}
    return {
        "id": snippet["id"],
        "language": snippet["language"],
        "difficulty": snippet["difficulty"],
        "code": snippet["code"],
        "difficulty_mult": languages.DIFFICULTY_MULT[snippet["difficulty"]],
        "hint_penalty": HINT_PENALTY,
        "source": source,
    }


@app.post("/api/round/{snippet_id}/hint")
async def reveal_hint(snippet_id: str, req: HintRequest):
    snippet = storage.get_snippet(snippet_id)
    if not snippet:
        raise HTTPException(status_code=404, detail="Раунд не найден")
    state = ACTIVE.setdefault(snippet_id, {"hints_used": 0})
    # Подсказки открываются по порядку, поэтому счётчик — это номер самой дальней открытой.
    state["hints_used"] = max(state["hints_used"], req.index + 1)
    return {
        "index": req.index,
        "text": snippet["hints"][req.index],
        "hints_used": state["hints_used"],
    }


@app.post("/api/round/{snippet_id}/answer")
async def submit_answer(snippet_id: str, req: AnswerRequest):
    snippet = storage.get_snippet(snippet_id)
    if not snippet:
        raise HTTPException(status_code=404, detail="Раунд не найден")
    if snippet_id in storage.seen_snippet_ids():
        raise HTTPException(status_code=409, detail="На этот фрагмент уже отвечали")

    answer = req.answer.strip()
    if not answer:
        raise HTTPException(status_code=400, detail="Пустой ответ")

    try:
        grade = await deepseek.grade_answer(
            language=snippet["language"],
            code=snippet["code"],
            reference=snippet["reference"],
            answer=answer,
        )
    except deepseek.DeepSeekError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    hints_used = ACTIVE.get(snippet_id, {}).get("hints_used", 0)
    mult = languages.DIFFICULTY_MULT[snippet["difficulty"]]
    points = round(grade["percent"] * (1 - HINT_PENALTY * hints_used) * mult)

    progress = storage.record_round(
        {
            "snippet_id": snippet_id,
            "language": snippet["language"],
            "difficulty": snippet["difficulty"],
            "percent": grade["percent"],
            "hints_used": hints_used,
            "points": points,
            "answer": answer,
        }
    )
    ACTIVE.pop(snippet_id, None)

    cards_added = storage.save_cards(
        _build_cards(grade["cards"], snippet["language"], source="round", snippet_id=snippet_id)
    )

    return {
        **grade,
        "reference": snippet["reference"],
        "hints_used": hints_used,
        "points": points,
        "difficulty_mult": mult,
        "passed": grade["percent"] >= PASS_PERCENT,
        "streak": progress["rounds"][-1]["streak_after"],
        "cards_added": cards_added,
        "stats": _full_stats(),
    }


@app.get("/api/cards/due")
async def cards_due():
    """Вся очередь на сегодня разом: карточки лёгкие, а листать их надо без задержек."""
    cards = [c for c in storage.load_cards().values() if srs.is_due(c)]
    # Сначала те, что уже учатся: новые не должны вытеснять просроченные повторы.
    cards.sort(key=lambda c: (c["reps"] == 0, c["due"]))
    return {
        "cards": [
            {
                "id": c["id"],
                "language": c["language"],
                "kind": c["kind"],
                "front": c["front"],
                "back": c["back"],
                "reps": c["reps"],
                "intervals": srs.preview_intervals(c),
            }
            for c in cards
        ],
        "stats": storage.card_stats(),
    }


@app.post("/api/cards/{card_id}/review")
async def review_card(card_id: str, req: ReviewRequest):
    card = storage.get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    try:
        state = srs.apply_review(card, req.rating)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    updated = storage.update_card(card_id, state)
    return {
        "id": card_id,
        "interval": updated["interval"],
        "due": updated["due"],
        "ease": updated["ease"],
        "again": req.rating == "again",  # карточка вернётся в конец очереди этой сессии
        "stats": storage.card_stats(),
    }


@app.post("/api/cards/deck")
async def make_deck(req: DeckRequest):
    if req.language not in languages.all_languages():
        raise HTTPException(status_code=400, detail=f"Неизвестный язык: {req.language}")
    have = [c["front"] for c in storage.load_cards().values() if c["language"] == req.language]
    try:
        raw = await deepseek.generate_deck(req.language, req.count, have)
    except deepseek.DeepSeekError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    added = storage.save_cards(_build_cards(raw, req.language, source="deck", snippet_id=None))
    return {"language": req.language, "added": added, "stats": storage.card_stats()}


@app.get("/api/languages")
async def get_languages():
    return {"languages": languages.all_languages()}


@app.get("/api/stats")
async def get_stats():
    return _full_stats()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
