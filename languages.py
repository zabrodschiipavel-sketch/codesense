"""Пулы языков. Сложность влияет и на выбор языка, и на сложность самого кода."""

import random

MAINSTREAM = [
    "Python", "JavaScript", "TypeScript", "Java", "C", "C++", "C#", "Go",
    "Rust", "Ruby", "PHP", "Swift", "Kotlin", "Dart", "Objective-C", "Scala",
]

SCRIPTING = [
    "Lua", "Perl", "Tcl", "Bash", "PowerShell", "AWK", "Julia", "R",
    "MATLAB", "Groovy", "sed", "Vimscript", "Emacs Lisp",
]

FUNCTIONAL = [
    "Haskell", "OCaml", "F#", "Elixir", "Erlang", "Clojure", "Scheme",
    "Common Lisp", "Elm", "Racket", "PureScript", "Gleam", "ReScript",
    "Standard ML", "Unison", "Roc",
]

SYSTEMS = [
    "Zig", "Nim", "D", "Odin", "Ada", "Fortran", "Crystal", "Pascal",
    "Modula-2", "Hare", "x86-64 Assembly", "ARM Assembly", "Vala", "Pony",
]

EXOTIC = [
    "APL", "J", "K", "BQN", "Forth", "Prolog", "Mercury", "Smalltalk",
    "COBOL", "Factor", "Io", "Rebol", "Red", "Eiffel", "Oz", "Idris",
    "Agda", "Coq", "Raku", "Verilog", "VHDL", "Chapel", "Futhark",
    "Solidity", "Move", "Cadence", "Ballerina", "Haxe", "Zsh", "PostScript",
    "Befunge", "Tcl/Tk", "Logo", "Scratch (текстовая нотация)", "Wolfram Language",
    "PL/SQL", "T-SQL", "Nix", "Dhall", "Jsonnet", "Starlark", "CUE",
]

# Для каждой сложности: список (пул, вес). Любой язык может выпасть, но перекос — по уровню.
POOLS = {
    "easy": [(MAINSTREAM, 70), (SCRIPTING, 30)],
    "medium": [(FUNCTIONAL, 40), (SYSTEMS, 30), (SCRIPTING, 20), (MAINSTREAM, 10)],
    "hard": [(EXOTIC, 60), (FUNCTIONAL, 20), (SYSTEMS, 20)],
}

DIFFICULTIES = ["easy", "medium", "hard"]

# Тему, как и язык, выбирает сервер. Просить модель «возьми что-нибудь другое» бесполезно:
# она всё равно скатывается к подсчёту слов. Явно названная тема эту колею ломает.
THEMES = [
    "разбор строки в структуру", "конечный автомат", "обход дерева",
    "поиск пути в графе", "мемоизация вычислений", "сортировка нестандартным компаратором",
    "бинарный поиск по границе", "операции над матрицами", "битовые трюки",
    "арифметика дат и интервалов", "пересечение и слияние интервалов", "LRU-кэш",
    "очередь с приоритетом", "пул ресурсов", "повтор с экспоненциальной задержкой",
    "ограничение частоты запросов", "разбор бинарного формата", "кодирование и сжатие",
    "контрольная сумма или хеш", "простой шифр", "дедупликация потока",
    "группировка и агрегация", "скользящее окно", "ленивая последовательность",
    "генератор комбинаций", "проверка входных данных", "разбор аргументов командной строки",
    "сравнение двух структур", "плоский обход вложенности", "координаты и геометрия",
    "клеточный автомат", "перевод единиц измерения", "циклический буфер",
    "объединение непересекающихся множеств", "топологическая сортировка",
    "выборка случайных элементов", "статистика по числам", "форматирование таблицы",
    "работа со списком задач", "транзакция с откатом",
]

RECENT_THEMES_WINDOW = 12

DIFFICULTY_MULT = {"easy": 1.0, "medium": 1.3, "hard": 1.6}

DIFFICULTY_BRIEF = {
    "easy": (
        "Простой, но не примитивный фрагмент: 6-12 строк. Одна понятная задача, "
        "решённая идиоматично для языка."
    ),
    "medium": (
        "Фрагмент средней сложности: 10-18 строк. Задействуй характерные для языка "
        "конструкции (сопоставление с образцом, каррирование, макросы, генераторы, "
        "трейты — что уместно), чтобы код нельзя было прочитать по наитию из C-подобного опыта."
    ),
    "hard": (
        "Плотный фрагмент: 8-20 строк. Опирайся на нетривиальную семантику языка — то, "
        "что человек без знания именно этого языка разберёт только через рассуждение о "
        "структуре. Но код должен оставаться осмысленным и решать реальную задачу, "
        "а не быть головоломкой ради головоломки."
    ),
}


def pick_difficulty(requested: str) -> str:
    if requested in DIFFICULTIES:
        return requested
    return random.choice(DIFFICULTIES)


def pick_language(difficulty: str, exclude: list[str]) -> str:
    """Случайный язык из пулов под сложность, по возможности не из недавних."""
    pools = POOLS[difficulty]
    weights = [w for _, w in pools]
    for _ in range(40):
        pool = random.choices([p for p, _ in pools], weights=weights)[0]
        lang = random.choice(pool)
        if lang not in exclude:
            return lang
    # Все недавние — берём любой, лишь бы не повторить прошлый раунд.
    pool = random.choices([p for p, _ in pools], weights=weights)[0]
    return random.choice(pool)


def pick_theme(exclude: list[str]) -> str:
    fresh = [t for t in THEMES if t not in exclude]
    return random.choice(fresh or THEMES)


def all_languages() -> list[str]:
    return sorted(set(MAINSTREAM + SCRIPTING + FUNCTIONAL + SYSTEMS + EXOTIC))
