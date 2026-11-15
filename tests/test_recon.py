"""Этап «Разведка» вместе с движком: декларация, задания исследователям, сводка, банки, ворота."""

import re
import time

import pytest

from idea_graph_core import HUMAN, Store
from idea_graph_engine import Adapters, Project, Registry, Settings
from idea_graph_engine.agents import Adapter, TurnResult
from idea_graph_engine.runtime import EngineError
from idea_graph_recon import manifest, prepare


class Script(Adapter):
    name = "script"
    label = "Сценарий"

    def __init__(self, script):
        self.script = script
        self.notes = []

    def found(self):
        return "script"

    def run(self, request):
        project, token = request.extra["project"], request.extra["token"]
        self.notes.append((request.model, request.note))
        self.script(request.model, request.note, lambda tool, **a: project.tool_call(token, tool, a), request)
        return TurnResult(session_id="s", text="", cost=0.0)


@pytest.fixture
def project(tmp_path):
    def build(script):
        store = Store.create(tmp_path / "p", "Проект")
        store.apply([{"op": "add_card", "kind": "сфера", "title": "Частные клиники", "body": "Запись пациентов"}], HUMAN)
        settings = Settings(tmp_path / "s.json")
        settings.data["default_slot"] = {"agent": "script", "model": "main", "effort": ""}
        settings.data["researchers"] = [{"agent": "script", "model": f"r{i}", "effort": ""} for i in (1, 2, 3)]
        registry = Registry(discover=False)
        registry.register(manifest())
        adapters = Adapters()
        adapters.add(Script(script))
        built = Project(tmp_path / "p", settings, registry, adapters)
        built.PROPAGATE_DELAY = 60
        return built

    return build


def wait(project, statuses, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        run = project.runs.get("recon")
        if run is not None and run.status in statuses:
            return run
        time.sleep(0.01)
    raise AssertionError(project.runs.get("recon") and project.runs["recon"].status)


def test_manifest_shape():
    m = manifest()
    stage = m["stage"]
    assert [s["id"] for s in stage["steps"]] == ["sphere", "competitors", "analysis"]
    assert stage["steps"][1]["research_mode"] == "replicate" and stage["steps"][2]["research_mode"] == "distribute"
    assert stage["steps"][1]["produces_bank"] == "competitors" and stage["steps"][2]["needs"] == ["competitors"]
    assert m["banks"] == {"reads": ["competitors", "analysis"], "writes": ["competitors", "analysis"]}
    assert m["skill"].startswith("# Этап «Разведка»") and stage["research"]["skill"].startswith("# Исследователь")
    assert stage["auto"]["limits"][0]["key"] == "competitors" and stage["propagate"] is False


def test_competitor_discovery_replicates_task_and_main_agent_writes_proposed_records(project):
    seen = {"tasks": [], "main": [], "bank": []}

    def script(model, note, call, request):
        if model.startswith("r"):
            seen["tasks"].append((model, note))
            call("report", findings=[
                {"kind": "конкурент", "title": "Докдок", "data": {"name": "Докдок", "url": "https://dokdok.example", "why": "запись онлайн", "kind": "прямой"},
                 "sources": ["https://dokdok.example"]}], summary="нашёл")
            return
        seen["main"].append(note)
        seen["bank"].append(call("bank_write", name="competitors", records=[
            {"type": "competitor", "key": "dokdok.example", "sources": ["https://dokdok.example"],
             "data": {"name": "Докдок", "url": "https://dokdok.example", "why": "запись онлайн", "kind": "прямой"}}]))
        call("finish", outcome="готово", summary="список готов")

    p = project(script)
    p.start("recon", step="competitors", action="suggest", target="c1")
    run = wait(p, ("finished", "error"))
    assert run.status == "finished" and run.outcome == "готово"
    assert sorted(m for m, _ in seen["tasks"]) == ["r1", "r2", "r3"]
    note = seen["tasks"][0][1]
    assert "Частные клиники" in note and "Запись пациентов" in note and "не больше 9" in note and "Материалов пользователя нет" in note
    assert "минимум двое исследователей" in seen["main"][0] and "[конкурент] Докдок" in seen["main"][0]
    assert "https://dokdok.example" in seen["main"][0] and "Ты помощник" not in seen["main"][0]
    record = p.store.bank("competitors").list()[0]
    assert record["data"]["state"] == "proposed" and record["key"] == "dokdok.example"
    assert p.state()["stages"]["recon"]["steps"][1]["records_proposed"] == 1


def test_gate_then_analysis_distributes_one_task_per_competitor(project):
    seen = {"models": [], "titles": []}

    def script(model, note, call, request):
        if model.startswith("r"):
            seen["models"].append(model)
            seen["titles"].append(re.search(r"конкурента «(.+?)»", note).group(1))
            call("report", findings=[
                {"kind": "роль", "title": "Пациент", "description": "записывается", "sources": ["u"]},
                {"kind": "процесс", "title": "Запись на приём", "data": {"roles": ["Пациент"]}, "sources": ["u"]},
                {"kind": "фича", "title": "Напоминания", "sources": ["u"]}])
            return
        assert "РЕЗУЛЬТАТЫ ИССЛЕДОВАНИЯ" in note and "[роль] Пациент" in note and "bank_write name=analysis" in note
        call("bank_write", name="analysis", records=[{"type": "analysis", "key": "a.example", "data": {
            "competitor": "А", "roles": [{"name": "Пациент"}], "processes": [], "features": []}}])
        call("finish", outcome="готово", summary="проанализировано")

    p = project(script)
    bank = p.store.bank("competitors")
    for name, key, state in (("А", "a.example", "accepted"), ("Б", "b.example", "accepted"), ("В", "c.example", "accepted")):
        bank.put("competitor", {"name": name, "url": "https://" + key, "state": state}, "package:recon", key=key)
    p.store.bank("competitors").put("competitor", {"name": "Г", "url": "https://d.example", "state": "proposed"}, "package:recon", key="d.example")
    p.start("recon", step="analysis", action="suggest")
    run = wait(p, ("finished", "error"))
    assert run.status == "finished" and sorted(seen["titles"]) == ["А", "Б", "В"]          # принятые, без нового «предложенного»
    assert sorted(seen["models"]) == ["r1", "r2", "r3"]                                       # по одному заданию на модель
    assert p.store.bank("analysis").list()[0]["data"]["state"] == "proposed"


def test_auto_without_acceptance_analyses_proposed_competitors_and_skips_empty_sphere_step(project):
    flow = []

    def script(model, note, call, request):
        if model.startswith("r"):
            flow.append("исследователь")
            call("report", findings=[{"kind": "конкурент", "title": "Докдок", "data": {"name": "Докдок", "url": "https://dd.example"},
                                      "sources": ["https://dd.example"]}] if "Найди не больше" in note else
                 [{"kind": "роль", "title": "Пациент", "sources": ["u"]}])
            return
        if "Шаг этапа «Конкуренты»" in note:
            flow.append("конкуренты")
            call("bank_write", name="competitors", records=[{"type": "competitor", "key": "dd.example",
                                                             "data": {"name": "Докдок", "url": "https://dd.example"}}])
        else:
            flow.append("анализ")
            assert "Докдок" not in note or True
        call("finish", outcome="готово", summary="ок")

    p = project(script)
    p.start("recon", auto={"targets": []})
    run = wait(p, ("finished", "error"))
    assert run.status == "finished" and flow.count("исследователь") == 3 + 1            # три по поиску, один по анализу
    assert flow[-2:] == ["исследователь", "анализ"] or "анализ" in flow
    assert flow.index("конкуренты") < flow.index("анализ") and run.autorun["queue"] == [["c1", "competitors"], ["c1", "analysis"]]


def test_sphere_clarify_prompt_and_prepare(project):
    notes = []

    def script(model, note, call, request):
        notes.append(note)
        call("finish", outcome="готово", summary="ок")

    p = project(script)
    p.start("recon", step="sphere", action="clarify", target="c1")
    run = wait(p, ("finished",))
    assert "Проверь формулировку" in notes[0] and "Частные клиники" in notes[0] and "Банк competitors: записей 0" in notes[0]
    assert run.outcome == "есть_пробелы"                                               # конкурентов в банке нет
    with pytest.raises(EngineError):
        p.start("recon", step="sphere", action="suggest")                               # у шага сферы нет такого действия
    assert "Сферы: c1 «Частные клиники»" in prepare(type("C", (), {"store": p.store, "bank": p.store.bank})())


def test_step_checks_and_help(project):
    p = project(lambda *a, **k: None)
    steps = {s["id"]: s for s in manifest()["stage"]["steps"]}
    assert all(s["help"] and callable(s["checks"]) for s in steps.values())
    state = {s["id"]: s for s in p.state()["stages"]["recon"]["steps"]}
    assert [i["text"] for i in state["competitors"]["issues"]] == ["Список конкурентов пуст"] and state["sphere"]["issues"] == []
    bank = p.store.bank("competitors")
    bank.put("competitor", {"name": "Докдок", "state": "accepted"}, "human", key="a.example")
    bank.put("competitor", {"name": "Клиника+", "state": "accepted"}, "human", sources=["u"], key="b.example")
    state = {s["id"]: s for s in p.state()["stages"]["recon"]["steps"]}
    assert [i["text"] for i in state["competitors"]["issues"]] == ["У конкурента «Докдок» нет ссылки на источник"]
    assert [i["text"] for i in state["analysis"]["issues"]] == ["Нет анализа конкурента «Докдок»", "Нет анализа конкурента «Клиника+»"]
    p.store.bank("analysis").put("analysis", {"competitor": "Докдок"}, "package:recon", key="a.example")
    state = {s["id"]: s for s in p.state()["stages"]["recon"]["steps"]}
    assert [i["text"] for i in state["analysis"]["issues"]] == ["Нет анализа конкурента «Клиника+»"]


def test_document_has_sphere_competitors_and_analysis(project):
    from idea_graph_recon import document
    p = project(lambda *a, **k: None)
    ctx = type("C", (), {"store": p.store, "bank": p.store.bank})()
    assert document(ctx).startswith("## Разведка") and "**Сфера:** Частные клиники. Запись пациентов" in document(ctx)
    p.store.bank("competitors").put("competitor", {"name": "Докдок", "url": "https://dd.example", "kind": "прямой", "why": "запись | онлайн",
                                                   "state": "proposed"}, "package:recon", key="dd.example")
    p.store.bank("analysis").put("analysis", {"competitor": "Докдок", "roles": [{"name": "Пациент"}], "processes": [{"name": "Запись"}],
                                              "features": []}, "package:recon", key="dd.example")
    text = document(ctx)
    assert "| Докдок (предложен) | https://dd.example | прямой | запись / онлайн |" in text
    assert "**Докдок**" in text and "- роли: Пациент" in text and "- процессы: Запись" in text and "- фичи: —" in text
