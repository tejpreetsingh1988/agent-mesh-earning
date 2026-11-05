"""Batch 23: diagram spec validation (mesh/kpi.py validate_diagram)."""
from mesh.kpi import validate_diagram


def _roblox():
    return {"nodes": [
        {"id": "p", "label": "Players", "role": "payer", "icon": "coin"},
        {"id": "c", "label": "Roblox", "role": "company"},
        {"id": "cr", "label": "Creators", "role": "partner-channel"},
    ], "edges": [
        {"from": "p", "to": "c", "kind": "money", "label": "buys Robux"},
        {"from": "c", "to": "cr", "kind": "money", "label": "revenue share"},
        {"from": "cr", "to": "p", "kind": "value", "label": "experiences"},
    ]}


def test_valid_spec_passes_icon_stripped_alias_mapped():
    out = validate_diagram(_roblox())
    assert out is not None
    assert [n["role"] for n in out["nodes"]] == ["payer", "company", "partner"]
    assert all("icon" not in n for n in out["nodes"])
    assert len(out["edges"]) == 3


def test_digit_label_kills_node_and_its_edges():
    spec = _roblox()
    spec["nodes"].append({"id": "s", "label": "250 shops", "role": "user"})
    spec["edges"].append({"from": "s", "to": "c", "kind": "money", "label": "pays"})
    out = validate_diagram(spec)
    assert out is not None
    assert all(n["id"] != "s" for n in out["nodes"])
    assert all(e["from"] != "s" for e in out["edges"])


def test_long_label_and_unknown_role_dropped():
    spec = _roblox()
    spec["nodes"][0]["label"] = "very loyal paying players here"
    spec["nodes"][2]["role"] = "supplier"
    # Payer node dropped (label too long), partner dropped (bad role);
    # remaining: company only + no usable edges -> None.
    assert validate_diagram(spec) is None


def test_company_count_must_be_exactly_one():
    spec = _roblox()
    spec["nodes"].append({"id": "c2", "label": "Subsidiary", "role": "company"})
    assert validate_diagram(spec) is None
    spec2 = _roblox()
    spec2["nodes"] = [n for n in spec2["nodes"] if n["role"] != "company"]
    assert validate_diagram(spec2) is None


def test_no_edges_or_single_node_is_none():
    spec = _roblox()
    spec["edges"] = []
    assert validate_diagram(spec) is None
    assert validate_diagram({"nodes": [{"id": "c", "label": "Co", "role": "company"}], "edges": []}) is None
    assert validate_diagram(None) is None
    assert validate_diagram({"nodes": "nope", "edges": []}) is None


def test_bad_edges_dropped_but_good_ones_survive():
    spec = _roblox()
    spec["edges"] += [
        {"from": "p", "to": "ghost", "kind": "money", "label": "pays"},
        {"from": "p", "to": "c", "kind": "gift", "label": "gift"},
        {"from": "p", "to": "c", "kind": "money", "label": "pays 100 dollars"},
    ]
    out = validate_diagram(spec)
    assert out is not None and len(out["edges"]) == 3


def test_empty_edge_label_kept():
    spec = _roblox()
    spec["edges"][0]["label"] = ""
    out = validate_diagram(spec)
    assert out is not None and out["edges"][0]["label"] == ""


def test_node_and_edge_caps_truncate():
    nodes = [{"id": "c", "label": "Co", "role": "company"}]
    nodes += [{"id": f"u{i}", "label": f"User{i}", "role": "user"} for i in range(10)]
    # User labels carry digits, so they are dropped, not truncated;
    # use digit-free labels to test the cap itself.
    nodes = [{"id": "c", "label": "Co", "role": "company"}]
    names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta", "Iota", "Kappa"]
    nodes += [{"id": f"u{i}", "label": names[i], "role": "user"} for i in range(10)]
    edges = [{"from": "u0", "to": "c", "kind": "money", "label": "pays"}]
    edges += [{"from": f"u{i}", "to": "c", "kind": "value", "label": "uses"} for i in range(1, 12)]
    out = validate_diagram({"nodes": nodes, "edges": edges})
    assert out is not None
    assert len(out["nodes"]) == 8  # company + first 7 users
    # Edges truncate to the first 10, then edges referencing the
    # truncated users (u7+) drop: u0..u6 survive.
    assert len(out["edges"]) == 7
