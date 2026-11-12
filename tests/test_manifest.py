from importlib import metadata

from ideagraph_research import manifest


def test_manifest_is_complete():
    m = manifest()
    assert m["id"] == "research" and m["kind"] == "agent" and m["outcomes"] == ["готово"]
    assert m["web_search"] is True
    for phrase in ['research.sources', 'опровергает', 'WebSearch', 'finish']:
        assert phrase in m["skill"]


def test_entry_point_is_declared():
    assert "research" in [p.name for p in metadata.entry_points(group="ideagraph.packages")]
