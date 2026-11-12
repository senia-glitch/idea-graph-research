"""Пакет «Исследование»: скилл и манифест. Агенту этого пакета оболочка открывает веб-поиск."""

from pathlib import Path

__version__ = "0.1.0"


def manifest() -> dict:
    return {
        "id": "research",
        "name": "Исследование",
        "description": "Ищет в сети конкурентов и факты, заменяет допущения проверенными данными. "
                       "Если факт спорит с принятым решением — задаёт вопрос.",
        "kind": "agent",
        "order": 20,
        "reads": ["идея", "ветка", "решение", "граница"],
        "writes": ["конкурент", "факт", "ветка"],
        "asks": True,
        "web_search": True,
        "model_level": "средняя",
        "outcomes": ["готово"],
        "fresh_session": True,
        "skill": (Path(__file__).parent / "skill.md").read_text(encoding="utf-8"),
    }
