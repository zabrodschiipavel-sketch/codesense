"""Сборка вариантов ответа для карточки.

Дистракторы берутся из оборотов других карточек — не выдумываются моделью. Это бесплатно,
мгновенно, работает без сети и, главное, даёт правдоподобность по построению: каждый неверный
вариант — настоящее описание настоящей конструкции этого же языка. Выбор из четырёх похожих
описаний перестаёт быть узнаванием и становится различением, а именно оно тут и тренируется.

Поэтому же кандидаты ранжируются: сначала тот же язык и тот же вид карточки (символ против
символа), и только потом всё остальное. Вариант из другого языка отсекается с одного взгляда
и вырождает вопрос.
"""

import random

OPTIONS = 4
MIN_OPTIONS = 2  # меньше двух — это уже не выбор, карточку лучше не показывать


def _tiers(card: dict, pool: list[dict]) -> list[list[dict]]:
    same_lang = [c for c in pool if c["language"] == card["language"]]
    other_lang = [c for c in pool if c["language"] != card["language"]]
    return [
        [c for c in same_lang if c["kind"] == card["kind"]],
        [c for c in same_lang if c["kind"] != card["kind"]],
        [c for c in other_lang if c["kind"] == card["kind"]],
        other_lang,
    ]


def build_options(card: dict, pool: list[dict], rng: random.Random | None = None):
    """(варианты, индекс правильного) либо None, если дистракторов не набралось."""
    rng = rng or random
    backs_seen = {card["back"].strip().lower()}
    candidates = [c for c in pool if c["id"] != card["id"]]

    distractors: list[str] = []
    for tier in _tiers(card, candidates):
        tier = tier[:]
        rng.shuffle(tier)
        for c in tier:
            key = c["back"].strip().lower()
            if key in backs_seen:
                continue
            backs_seen.add(key)
            distractors.append(c["back"])
            if len(distractors) == OPTIONS - 1:
                break
        if len(distractors) == OPTIONS - 1:
            break

    if len(distractors) + 1 < MIN_OPTIONS:
        return None

    options = distractors + [card["back"]]
    rng.shuffle(options)
    return options, options.index(card["back"])
