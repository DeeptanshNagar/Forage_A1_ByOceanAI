import pytest

from forge.schemas import Requirements, ToolNeed
from forge.stages.generator import prune_unjustified, select_tools
from forge.tools.calculator import CalcError, safe_eval
from forge.tools.csv_lookup import lookup
from forge.tools.http_api import HostNotAllowed, safe_get
from forge.tools.registry import Tool, ToolRegistry, default_registry, discover


def test_discovery_finds_all_tools():
    reg = discover()
    for name in ("csv_lookup", "calculator", "http_api", "current_date", "unit_converter", "web_search_stub",
                 "email_sender_stub", "file_writer_stub"):
        assert name in reg


def test_hr_like_requirements_get_no_weather_or_http_tool(cooking_ctx):
    req = Requirements(purpose="Answer staff questions about leave, travel rules and grievances using HR policies",
                       must_answer_topics=["annual leave", "travel per diem", "grievance procedure"], brief="b")
    tools, log = select_tools(cooking_ctx, req)
    names = [t.name for t in tools]
    assert "http_api" not in names and "web_search_stub" not in names
    assert names == []
    assert log["proposed"]  # the mock model proposed something unjustified ...
    assert log["pruned"]  # ... and the deterministic validator removed it


def test_catalogue_requirements_get_csv_lookup_and_calculator(tmp_path, settings):
    from forge.context import RunContext

    from .conftest import make_docs

    folder = make_docs(tmp_path / "d", {"parts.csv": "part_no,price\nX-1,10\nX-2,20\n"})
    ctx = RunContext(tmp_path / "r", settings, docs_path=str(folder))
    req = Requirements(purpose="Find parts and compute order totals", must_answer_topics=["parts"], brief="b",
                       tool_needs=[ToolNeed(capability="tabular_lookup", justification="catalogue CSV", requirement_ref="T1"),
                                   ToolNeed(capability="arithmetic", justification="order totals", requirement_ref="T2")])
    tools, log = select_tools(ctx, req)
    assert sorted(t.name for t in tools) == ["calculator", "csv_lookup"]
    assert tools[[t.name for t in tools].index("csv_lookup")].config["csv_paths"]
    assert all(t.justification and t.requirement_ref in ("T1", "T2") for t in tools)
    assert prune_unjustified(tools, req, ctx) == tools


def test_no_unjustified_tool_survives_pruning(cooking_ctx):
    from forge.schemas import ToolBinding

    req = Requirements(purpose="p", brief="b", tool_needs=[ToolNeed(capability="arithmetic", requirement_ref="T1")])
    tools = [ToolBinding(name="calculator", justification="totals", requirement_ref="T1"),
             ToolBinding(name="http_api", justification="might be handy", requirement_ref="A1"),
             ToolBinding(name="web_search_stub", justification="x", requirement_ref="T1")]
    assert [t.name for t in prune_unjustified(tools, req, cooking_ctx)] == ["calculator"]


def test_registry_scales_to_300_plus_tools(cooking_ctx):
    reg = discover()
    domains = ["crm", "billing", "hr_portal", "fleet", "warehouse", "ticketing", "marketing", "geo", "media", "iot"]
    verbs = ["lookup", "update", "delete", "export", "sync", "notify", "translate", "summarize", "schedule", "archive"]
    for i in range(320):
        d, v = domains[i % 10], verbs[(i // 10) % 10]
        reg.register(Tool(f"{d}_{v}_{i}", f"{v.capitalize()} {d.replace('_', ' ')} records in the {d} system (variant {i}).",
                          [f"{d}_{v}"], {"type": "object"}, lambda a, c: None))
    assert len(reg) > 300
    cooking_ctx.registry = reg
    from .conftest import make_docs

    folder = make_docs(cooking_ctx.run_dir.parent / "csvdocs", {"t.csv": "a,b\n1,2\n"})
    cooking_ctx.docs_path, cooking_ctx._docs = str(folder), None
    req = Requirements(purpose="Look up rows in a table and compute totals", brief="b", must_answer_topics=["rows"],
                       tool_needs=[ToolNeed(capability="tabular_lookup", justification="table", requirement_ref="T1"),
                                   ToolNeed(capability="arithmetic", justification="totals", requirement_ref="T2")])
    tools, log = select_tools(cooking_ctx, req)
    assert sorted(t.name for t in tools) == ["calculator", "csv_lookup"]
    assert len(log["shortlist"]) <= 8  # the LLM never sees all 300+ descriptions
    assert log["registry_size"] > 300


def test_calculator_basic_and_safety():
    assert safe_eval("12 * 45.5 + 3") == 549.0
    assert safe_eval("round(1500 * 0.97, 2)") == 1455.0
    assert safe_eval("2^3") == 8
    for bad in ['__import__("os").system("x")', "open('f')", "(lambda: 1)()", "2 ** 100000", "a + 1",
                "[x for x in range(9)]", "().__class__", "1/0", ""]:
        with pytest.raises(CalcError):
            safe_eval(bad)


def test_csv_lookup_filters_fuzzy_and_aggregate(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("part_no,description,price,stock\nAB-1,Fuel filter,10.5,3\nAB-2,Oil filter,7,0\nCD-9,Pump seal,99,5\n")
    cfg = {"csv_paths": [str(p)]}
    r = lookup({"filters": [{"column": "part no", "op": "==", "value": "ab-2"}]}, cfg)
    assert r["rows"][0]["_row"] == 2 and r["rows"][0]["description"] == "Oil filter"
    r = lookup({"filters": {"stock": "0"}}, cfg)
    assert [x["part_no"] for x in r["rows"]] == ["AB-2"]
    r = lookup({"filters": [{"column": "price", "op": ">", "value": 8}], "aggregate": {"op": "sum", "column": "price"}}, cfg)
    assert r["rows"][0]["value"] == 109.5
    r = lookup({"query": "pump seel"}, cfg)
    assert r["rows"][0]["part_no"] == "CD-9"


def test_http_api_allowlist():
    with pytest.raises(HostNotAllowed):
        safe_get("https://evil.example.com/steal", {})
    with pytest.raises(HostNotAllowed):
        safe_get("http://api.open-meteo.com/v1/forecast", {})  # https only


def test_tool_run_never_raises():
    out = default_registry().get("calculator").run({"expression": "1/0"})
    assert out["ok"] is False and "division" in out["error"]
