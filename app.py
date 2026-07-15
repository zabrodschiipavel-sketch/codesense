"""CodeSense — тренажёр насмотренности: читаешь чужой код на случайном языке и объясняешь словами."""

import pathlib
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import deepseek
import languages
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

    return {
        **grade,
        "reference": snippet["reference"],
        "hints_used": hints_used,
        "points": points,
        "difficulty_mult": mult,
        "passed": grade["percent"] >= PASS_PERCENT,
        "streak": progress["rounds"][-1]["streak_after"],
        "stats": storage.stats(),
    }


@app.get("/api/stats")
async def get_stats():
    return storage.stats()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
