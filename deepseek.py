"""Клиент DeepSeek: генерация сниппета и оценка разбора."""

import json
import os
import re

import httpx

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = os.getenv("CODESENSE_MODEL", "deepseek-v4-flash")

# flash размышляет по умолчанию; reasoning_effort принимает low|medium|high|max|xhigh,
# "off" отключает размышления совсем (thinking.type=disabled).
# Замерено на этом промпте: генерация с размышлениями 30-70 с, без них 6-9 с при том же
# качестве кода — писать идиоматичный фрагмент модель и так умеет, думать тут не над чем.
# Оценка свободного текста против кода — наоборот, самое трудное здесь, ей нужен high.
REASONING_GENERATE = os.getenv("CODESENSE_REASONING_GENERATE", "off")
REASONING_GRADE = os.getenv("CODESENSE_REASONING_GRADE", "high")
REASONING_OFF = "off"

TIMEOUT = 180.0


class DeepSeekError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise DeepSeekError(
            "DEEPSEEK_API_KEY не задан. Выполни: setx DEEPSEEK_API_KEY \"<ключ>\" "
            "и перезапусти терминал."
        )
    return key


def _extract_json(text: str) -> dict:
    """Модели любят обернуть JSON в ```json ... ``` или добавить преамбулу."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise DeepSeekError(f"Ответ модели не разбирается как JSON: {exc}") from exc
    raise DeepSeekError("В ответе модели нет JSON-объекта")


async def _chat(system: str, user: str, temperature: float, reasoning: str) -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    if reasoning == REASONING_OFF:
        payload["thinking"] = {"type": "disabled"}
    else:
        payload["reasoning_effort"] = reasoning
    headers = {"Authorization": f"Bearer {_api_key()}"}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(API_URL, json=payload, headers=headers)
    if resp.status_code != 200:
        raise DeepSeekError(f"DeepSeek HTTP {resp.status_code}: {resp.text[:500]}")
    body = resp.json()
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise DeepSeekError(f"Неожиданная форма ответа: {json.dumps(body)[:500]}") from exc
    return _extract_json(content)


GENERATE_SYSTEM = (
    "Ты — составитель упражнений на чтение кода. Ты отлично знаешь десятки языков "
    "программирования, включая редкие, и пишешь на каждом строго идиоматично — так, как "
    "написал бы опытный носитель этого языка, а не как перевод с Python. "
    "Отвечаешь только валидным JSON-объектом, без пояснений вокруг."
)


def _generate_prompt(language: str, difficulty: str, brief: str, theme: str) -> str:
    return f"""Составь упражнение на понимание кода.

Язык: {language}
Уровень: {difficulty}
Тема: {theme}
Каким должен быть фрагмент: {brief}

Тема задана жёстко — не подменяй её. Если она плохо ложится на {language}, возьми ближайшую
осмысленную для этого языка трактовку темы, но не переключайся на другую задачу.

Жёсткие требования к полю code:
- Настоящий, синтаксически корректный {language}. Идиоматичный для {language}, а не C-подобная калька.
- НИКАКИХ комментариев в коде. Ни одного. Комментарий — это готовый ответ.
- Никаких docstring'ов и поясняющих строк.
- Имена переменных и функций — правдоподобные и идиоматичные, но не пересказывающие задачу.
  Плохо: calculate_fibonacci_sequence, user_email_validator. Хорошо: fib, valid, acc, xs, rows.
- Фрагмент самодостаточен: по нему можно понять, что происходит, без остального проекта.
- Он должен решать осмысленную задачу, а не печатать "Hello, world".

Три подсказки открываются по очереди и раскрывают смысл постепенно:
- Первая — только синтаксис: расшифруй непривычные для {language} операторы и конструкции,
  встречающиеся во фрагменте, что означает каждый необычный символ. НЕ говори, что делает код в целом.
- Вторая — контекст: из какой области задача, какие структуры данных задействованы, какие
  функции языка вызываются и что возвращают. Всё ещё не раскрывай итоговый смысл.
- Третья — наводка: опиши логику по шагам почти до конца, но не называй итоговый результат
  одной фразой. Оставь последний шаг за читателем.

Каждая подсказка — сразу текст по существу, 1-3 предложения. Не нумеруй их внутри текста и не
начинай со слов «Подсказка», «Синтаксис:», «Контекст:» — нумерацию и заголовки рисует интерфейс.

Верни JSON ровно такой формы:
{{
  "code": "исходный код фрагмента, переводы строк как \\n",
  "topic": "2-4 слова: что этот код делает, для внутреннего учёта",
  "hints": ["текст первой подсказки", "текст второй подсказки", "текст третьей подсказки"],
  "reference": "Эталонный разбор, 3-6 предложений: что код делает в целом, как именно, и какая деталь языка тут ключевая. Показывается только после ответа."
}}

Подсказки и reference — на русском языке. Код — на {language}."""


async def generate_snippet(language: str, difficulty: str, brief: str, theme: str) -> dict:
    data = await _chat(
        GENERATE_SYSTEM,
        _generate_prompt(language, difficulty, brief, theme),
        temperature=1.0,
        reasoning=REASONING_GENERATE,
    )
    code = (data.get("code") or "").strip()
    hints = data.get("hints") or []
    reference = (data.get("reference") or "").strip()
    if not code:
        raise DeepSeekError("Модель вернула пустой код")
    if not isinstance(hints, list) or len(hints) < 3:
        raise DeepSeekError(f"Ожидалось 3 подсказки, пришло: {hints!r}")
    if not reference:
        raise DeepSeekError("Модель не вернула эталонный разбор")
    return {
        "code": code,
        "topic": (data.get("topic") or "").strip(),
        "hints": [str(h).strip() for h in hints[:3]],
        "reference": reference,
    }


GRADE_SYSTEM = (
    "Ты — строгий, но честный экзаменатор по чтению кода. Ты оцениваешь ровно одно: "
    "насколько человек понял, что делает код. Отвечаешь только валидным JSON-объектом."
)


def _grade_prompt(language: str, code: str, reference: str, answer: str) -> str:
    return f"""Оцени, насколько человек понял код.

Язык: {language}

Код:
```
{code}
```

Эталонный разбор (истина, человек его не видел):
{reference}

Ответ человека своими словами:
\"\"\"{answer}\"\"\"

Как оценивать:
- Оценивай ТОЛЬКО понимание смысла кода. Орфография, грамматика, корявость формулировок,
  отсутствие терминов — не штрафуются. Человек может назвать вещи своими словами.
- Не требуй знания названий конструкций языка. Если он описал поведение верно, но не знает,
  что это называется «каррирование» — это полный балл за этот пункт.
- Главное — итоговый смысл: что на входе, что происходит, что на выходе. Это основа оценки.
- Механика (как именно язык это делает) — вторично, но добавляет к оценке.
- Если человек уверенно утверждает неверное — снижай, это хуже, чем «не знаю».
- Ответ «не знаю» / пустой / не по делу — percent от 0 до 10.
- Не завышай из вежливости. 100 — только если разобрано и что, и как, без ошибок.

Шкала percent:
0-20 — не понял; 21-40 — уловил отдельные куски, целое не собрал;
41-60 — понял в общих чертах, механика мимо; 61-80 — верно понял, что делает, детали неточны;
81-95 — понял и что, и как, мелкие огрехи; 96-100 — исчерпывающе.

Верни JSON ровно такой формы:
{{
  "percent": <целое число 0-100>,
  "verdict": "одна фраза-приговор на русском, по делу, без похвалы ради похвалы",
  "correct": ["что человек уловил верно — короткие пункты, максимум 4; пустой список, если ничего"],
  "missed": ["что упустил или понял неверно — короткие пункты, максимум 4; пустой список, если всё верно"],
  "key_insight": "одно предложение: та деталь языка или логики, ради которой стоило смотреть на этот фрагмент"
}}

Всё — на русском языке."""


async def grade_answer(language: str, code: str, reference: str, answer: str) -> dict:
    data = await _chat(
        GRADE_SYSTEM,
        _grade_prompt(language, code, reference, answer),
        temperature=0.2,
        reasoning=REASONING_GRADE,
    )
    try:
        percent = int(round(float(data.get("percent", 0))))
    except (TypeError, ValueError):
        raise DeepSeekError(f"percent не число: {data.get('percent')!r}")
    percent = max(0, min(100, percent))
    return {
        "percent": percent,
        "verdict": (data.get("verdict") or "").strip(),
        "correct": [str(x) for x in (data.get("correct") or [])][:4],
        "missed": [str(x) for x in (data.get("missed") or [])][:4],
        "key_insight": (data.get("key_insight") or "").strip(),
    }
