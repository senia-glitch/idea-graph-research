"""Этап «Разведка»: сфера → список конкурентов → анализ → общий банк.

Что делает: по сфере бизнеса, которую пишет человек, находит реальных конкурентов и аналоги, после
одобрения человеком списка анализирует каждого (роли в системе, бизнес-процессы, уникальные фичи)
и складывает результат в банки проекта ``competitors`` и ``analysis`` — их читают следующие этапы.

Кто что делает: поиск ведут исследователи (несколько агентов на разных моделях, веб-поиск и ресурсы
пользователя), результат сводит и записывает основной агент, список правит и утверждает человек.
Весь код этапа — это декларация (шаги, виды карточек, банки, промпты): механику запускает движок.
"""

from __future__ import annotations

from pathlib import Path

from idea_graph_core import normalize_url

__version__ = "0.2.0"

SPHERE = "сфера"
COMPETITORS, ANALYSIS = "competitors", "analysis"
COMPETITOR_KINDS = ("прямой", "косвенный", "аналог")
DEFAULT_LIMIT = 6
HERE = Path(__file__).parent


def _read(name: str) -> str:
    return (HERE / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------- вспомогательное

def spheres(store) -> list[dict]:
    return sorted((c for c in store.cards.values() if c["kind"] == SPHERE), key=lambda c: int(c["id"][1:]))


def sphere_text(card: dict | None) -> str:
    if card is None:
        return "сфера не указана"
    body = (card.get("body") or "").strip()
    return f"«{card['title']}»" + (f". Подробности от пользователя: {body}" if body else "")


def limit(ctx) -> int:
    manifest = ctx.registry.get("recon") or {}
    try:
        return int(ctx.host.settings.auto_limits(manifest).get("competitors", DEFAULT_LIMIT))
    except Exception:  # noqa: BLE001 — настройки не должны ронять исследование
        return DEFAULT_LIMIT


def accepted_competitors(ctx) -> list[dict]:
    """Кого анализировать: принятых человеком; если он ничего не принимал (автоматический режим) — предложенных."""
    records = ctx.bank(COMPETITORS).list("competitor")
    accepted = [r for r in records if (r["data"] or {}).get("state") == "accepted"]
    return accepted or [r for r in records if (r["data"] or {}).get("state") == "proposed"]


def _materials(materials: list[dict]) -> str:
    if not materials:
        return "Материалов пользователя нет: ищи в сети."
    return "Материалы пользователя (используй их и проверь по сети):\n" + "\n\n".join(
        f"--- {m['title']} ---\n{m['text']}" for m in materials)


# ---------------------------------------------------------------------- исследование

def tasks(ctx, step: dict, target: dict | None, materials: list[dict]) -> list[dict]:
    """Задания исследователям: поиск конкурентов (всем одно) или анализ (по конкуренту на задание)."""
    card = target if target and target["kind"] == SPHERE else (spheres(ctx.store) or [None])[0]
    sphere = sphere_text(card)
    if step["id"] == "competitors":
        return [{"title": "поиск конкурентов", "note": "\n\n".join([
            f"Сфера бизнеса, подлежащая автоматизации: {sphere}.",
            f"Найди не больше {limit(ctx) + 3} реальных, действующих конкурентов и аналогов в этой сфере: готовые "
            "системы и сервисы, которые автоматизируют то же. Для каждого — kind «конкурент», title — название, "
            "data: {name, url (адрес сайта), why (одна фраза: чем релевантен), kind: «прямой», «косвенный» или «аналог»}, "
            "sources — адреса страниц, где ты это увидел.",
            _materials(materials)])}]
    if step["id"] == "analysis":
        out = []
        for record in accepted_competitors(ctx):
            data = record["data"]
            out.append({"title": data.get("name") or record["key"], "note": "\n\n".join([
                f"Сфера бизнеса: {sphere}.",
                f"Проанализируй конкурента «{data.get('name')}» ({data.get('url') or 'адрес не указан'}); "
                f"чем релевантен: {data.get('why') or '—'}. Изучи его сайт, документацию, обзоры и отзывы.",
                "Сообщи находки трёх видов: kind «роль» — роль участника в его системе (title — название роли, "
                "description — что делает); kind «процесс» — бизнес-процесс, который система автоматизирует "
                "(title — ситуация одной строкой, data: {roles: [названия ролей]}); kind «фича» — уникальная возможность "
                "(title, description). У каждой находки в sources — страницы, где ты это увидел.",
                _materials(materials)])})
        return out
    return []


def _collect(results: list[dict]) -> list[str]:
    lines: list[str] = []
    for item in results:
        lines.append(f"\nЗадание «{item['task']['title']}»:")
        if not item["reports"]:
            lines.append("  (исследователи не прислали отчёт)")
        for report in item["reports"]:
            lines.append(f"  {report.get('who', 'исследователь')}"
                         + (f" — {report['summary']}" if report.get("summary") else ""))
            for finding in report["findings"]:
                data = finding.get("data") or {}
                extra = ("; " + ", ".join(f"{k}={v}" for k, v in data.items())) if data else ""
                lines.append(f"    [{finding.get('kind') or 'находка'}] {finding['title']}"
                             + (f" — {finding['description']}" if finding.get("description") else "") + extra
                             + (f" [источники: {', '.join(finding['sources'])}]" if finding.get("sources") else " [без источника]"))
    return lines


def merge(ctx, step: dict, target: dict | None, results: list[dict]) -> str:
    """Вводные основному агенту: отчёты исследователей и правила, как их свести и записать в банк."""
    if step["id"] == "competitors":
        rules = [
            "РЕЗУЛЬТАТЫ ИССЛЕДОВАНИЯ: несколько исследователей независимо искали конкурентов в сети и в материалах пользователя.",
            f"Своди так: возьми тех, кого назвали минимум двое исследователей ИЛИ у кого есть рабочая ссылка; одинаковых "
            f"объединяй; оставь не больше {limit(ctx)} самых релевантных. Сначала прочитай банк (bank_read name=competitors), "
            "уже записанных не дублируй. Запиши через bank_write name=competitors: type «competitor», key — адрес сайта без "
            "схемы и «www.», data {name, url, why, kind}, sources — реальные ссылки из отчётов. Ничего не выдумывай.",
        ]
    else:
        rules = [
            "РЕЗУЛЬТАТЫ ИССЛЕДОВАНИЯ: каждого конкурента анализировал один исследователь. Сверяй находки с источниками.",
            "Для каждого конкурента запиши через bank_write name=analysis одну запись: type «analysis», key — тот же адрес, что у "
            "конкурента в банке competitors, data {competitor, roles: [{name, description}], processes: [{name, description, "
            "roles: [названия]}], features: [{name, description}]}, sources — реальные ссылки из отчёта. Находки без "
            "источников отбрасывай. Названия ролей приводи к общему виду («Пациент», а не «клиент клиники»).",
        ]
    return "\n".join(rules + _collect(results))


# ---------------------------------------------------------------------- промпты шагов

def _p_sphere_clarify(ctx, step, target) -> str:
    card = target or (spheres(ctx.store) or [None])[0]
    return (f"Сфера: {sphere_text(card)}. Проверь формулировку: понятно ли, какой бизнес и что именно автоматизируется. "
            "Если не хватает уточнений, задай до трёх вопросов с вариантами через ask (по одному за ход); "
            "формулировку человека сам не меняй.")


def _p_competitors_suggest(ctx, step, target) -> str:
    return ("Предложи список конкурентов для банка. Если во вводных ниже есть результаты исследования — своди их и "
            "запиши в банк competitors (правила в сводке). Если результатов нет — исследования не было: скажи об этом "
            "в finish и предложи человеку вручную добавить конкурентов во вкладке карты этапа. Записанное агентом "
            "остаётся предложенным: утверждает человек.")


def _p_competitors_review(ctx, step, target) -> str:
    return ("Проверь список конкурентов (bank_read name=competitors): нет ли явно пропущенных крупных игроков, "
            "не попали ли нерелевантные, есть ли у каждого рабочая ссылка. Замечания оставь карточками «замечание» "
            "(parent — карточка сферы), в теле укажи запись банка и что не так.")


def _p_competitors_clarify(ctx, step, target) -> str:
    return ("Проверь согласованность списка конкурентов со сферой и задай человеку через ask вопросы там, где неясно: "
            "прямой это конкурент или аналог, нужен ли он в списке.")


def _p_analysis_suggest(ctx, step, target) -> str:
    count = len(accepted_competitors(ctx))
    if not count:
        return ("В банке competitors нет конкурентов: анализировать некого. Скажи об этом в finish и попроси "
                "человека составить и утвердить список конкурентов.")
    return (f"Проанализируй конкурентов из списка ({count}). Если во вводных ниже есть результаты исследования — своди их и "
            "запиши в банк analysis (правила в сводке). Результат читают следующие этапы, поэтому названия ролей и процессов "
            "должны быть единообразными. Записанное остаётся предложенным: утверждает человек.")


def _p_analysis_review(ctx, step, target) -> str:
    return ("Проверь анализ (bank_read name=analysis и competitors): у каждого принятого конкурента есть запись, роли и "
            "процессы названы единообразно, у находок есть источники. Замечания оставь карточками «замечание» (parent — "
            "карточка сферы), в теле укажи запись и что не так.")


def _p_analysis_clarify(ctx, step, target) -> str:
    return ("Проверь согласованность анализа: одинаковые ли роли названы по-разному у разных конкурентов, нет ли противоречий. "
            "Спорные места вынеси человеку через ask с вариантами единого названия.")


# ---------------------------------------------------------------------- проверки шагов (открытые вопросы)

def _checks_sphere(ctx, step) -> list[str]:
    return [] if spheres(ctx.store) else ["Сфера не написана: нажмите «+ Сфера» вверху"]


def _checks_competitors(ctx, step) -> list[str]:
    records = ctx.bank(COMPETITORS).list("competitor")
    if not records:
        return ["Список конкурентов пуст"]
    return [f"У конкурента «{(r['data'] or {}).get('name') or r['key']}» нет ссылки на источник" for r in records if not r["sources"]]


def _checks_analysis(ctx, step) -> list[str]:
    done = {r["key"] for r in ctx.bank(ANALYSIS).list("analysis")}
    return [f"Нет анализа конкурента «{(r['data'] or {}).get('name') or r['key']}»" for r in accepted_competitors(ctx) if r["key"] not in done]


# ---------------------------------------------------------------------- документ

def _cell(value) -> str:
    return " ".join(str(value or "").split()).replace("|", "/") or "—"


def _names(items) -> str:
    return ", ".join(str(x.get("name") if isinstance(x, dict) else x) for x in (items or []) if x) or "—"


def document(ctx) -> str:
    """Раздел «Разведка» для документа: сфера, список конкурентов, анализ."""
    found = spheres(ctx.store)
    comp = ctx.bank(COMPETITORS).list("competitor")
    analysis = ctx.bank(ANALYSIS).list("analysis")
    if not (found or comp or analysis):
        return ""
    lines = ["## Разведка", ""]
    for card in found:
        lines += [f"**Сфера:** {card['title']}" + (f". {card['body'].strip()}" if (card.get("body") or "").strip() else ""), ""]
    if comp:
        lines += ["### Конкуренты", "", "| Название | Сайт | Тип | Чем релевантен |", "|---|---|---|---|"]
        for r in comp:
            d = r["data"] or {}
            mark = "" if d.get("state") == "accepted" else " (предложен)"
            lines.append(f"| {_cell(d.get('name'))}{mark} | {_cell(d.get('url'))} | {_cell(d.get('kind'))} | {_cell(d.get('why'))} |")
        lines.append("")
    if analysis:
        lines += ["### Анализ конкурентов", ""]
        for r in analysis:
            d = r["data"] or {}
            lines += [f"**{_cell(d.get('competitor') or r['key'])}**", f"- роли: {_names(d.get('roles'))}",
                      f"- процессы: {_names(d.get('processes'))}", f"- фичи: {_names(d.get('features'))}", ""]
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------- вводные и итог

def prepare(ctx) -> str:
    lines = ["Этап «Разведка»."]
    found = spheres(ctx.store)
    lines.append("Сферы: " + ("; ".join(f"{c['id']} «{c['title']}»" for c in found) if found else "ещё не написаны (их пишет человек)."))
    comp = ctx.bank(COMPETITORS).list("competitor")
    analysis = ctx.bank(ANALYSIS).list("analysis")
    lines.append(f"Банк competitors: записей {len(comp)}, принято {sum(1 for r in comp if r['data'].get('state') == 'accepted')}. "
                 f"Банк analysis: записей {len(analysis)}.")
    return "\n".join(lines)


def conclude(ctx, outcome: str) -> str:
    return "готово" if ctx.bank(COMPETITORS).list("competitor") else "есть_пробелы"


def auto_note(ctx, targets: list[dict], limits: dict | None) -> str:
    names = "; ".join(f"{c['id']} «{c['title']}»" for c in targets)
    cap = f"не больше {limits['competitors']} конкурентов" if limits else "число конкурентов не ограничено, но только релевантные и подтверждённые"
    return ("АВТОМАТИЧЕСКИЙ РЕЖИМ. Человека рядом нет. Работай только со сферами: " + names + ". "
            f"Для каждой сферы по очереди предложи список конкурентов ({cap}) и проанализируй их. "
            "Развилки решай сам; если выбор неочевиден и от него многое зависит, задай ровно один вопрос через ask: "
            "на него ответит совет из трёх агентов. Записанное остаётся предложенным: утверждает человек. "
            "Не делай работу ради работы: только подтверждённое источниками.")


def manifest() -> dict:
    return {
        "id": "recon",
        "name": "Разведка",
        "description": "Находит реальных конкурентов вашей сферы, анализирует их роли, процессы и фичи и складывает результат "
                       "в общий банк проекта.",
        "kind": "agent",
        "order": 4,
        "model_level": "сильная",
        "outcomes": ["готово", "есть_пробелы"],
        "skill": _read("skill.md"),
        "web_search": False,
        "banks": {"reads": [COMPETITORS, ANALYSIS], "writes": [COMPETITORS, ANALYSIS]},
        "prepare": prepare,
        "conclude": conclude,
        "document": document,
        "stage": {
            "roots": SPHERE,
            "propagate": False,
            "kinds": [{"kind": SPHERE, "title": "Сфера", "color": "#e8833a"}],
            "steps": [
                {"id": "sphere", "title": "Сфера", "question": "Напишите сферу бизнеса, подлежащего автоматизации.",
                 "help": "Напишите сферу бизнеса одной-двумя фразами: по ней ищутся конкуренты и строятся роли. Помощник может проверить формулировку.",
                 "phase": "Разведка", "produces": [SPHERE], "needs": [], "prompts": {"clarify": _p_sphere_clarify}, "checks": _checks_sphere},
                {"id": "competitors", "title": "Конкуренты",
                 "question": "Поиск конкурентов: правьте список и утвердите его.",
                 "help": "Помощник найдёт реальных конкурентов и аналоги в сети (три исследователя на разных моделях). Вы правите список: "
                         "принимаете нужных, удаляете лишних, добавляете своих. Запускать можно сколько угодно раз: новые находки дополнят список.",
                 "phase": "Разведка", "label": "Найти конкурентов",
                 "checks": _checks_competitors, "produces": [], "produces_bank": COMPETITORS, "needs": ["sphere"], "research": True,
                 "research_mode": "replicate", "target_kind": SPHERE,
                 "bank": {"name": COMPETITORS, "type": "competitor", "fields": [
                     {"key": "name", "title": "Название"}, {"key": "url", "title": "Сайт"},
                     {"key": "why", "title": "Чем релевантен"},
                     {"key": "kind", "title": "Тип", "values": list(COMPETITOR_KINDS)}]},
                 "prompts": {"suggest": _p_competitors_suggest, "review": _p_competitors_review,
                             "clarify": _p_competitors_clarify}},
                {"id": "analysis", "title": "Анализ конкурентов",
                 "question": "Роли в системе, бизнес-процессы и уникальные фичи каждого конкурента.",
                 "help": "Для каждого конкурента из списка собираются роли, бизнес-процессы и уникальные фичи. Результат ложится в общий банк и "
                         "подсказывает роли и сценарии следующей части.",
                 "phase": "Разведка", "label": "Проанализировать конкурентов",
                 "checks": _checks_analysis, "produces": [], "produces_bank": ANALYSIS, "needs": ["competitors"], "research": True,
                 "research_mode": "distribute", "target_kind": SPHERE,
                 "bank": {"name": ANALYSIS, "type": "analysis", "fields": [
                     {"key": "competitor", "title": "Конкурент"}, {"key": "roles", "title": "Роли", "list": True},
                     {"key": "processes", "title": "Процессы", "list": True},
                     {"key": "features", "title": "Фичи", "list": True}]},
                 "prompts": {"suggest": _p_analysis_suggest, "review": _p_analysis_review, "clarify": _p_analysis_clarify}},
            ],
            "auto": {"targets": SPHERE, "note": auto_note,
                     "limits": [{"key": "competitors", "name": "Конкурентов в списке, не больше", "default": DEFAULT_LIMIT}]},
            "research": {"skill": _read("research_skill.md"), "tasks": tasks, "merge": merge, "mode": "replicate"},
        },
    }


__all__ = ["manifest", "normalize_url"]
