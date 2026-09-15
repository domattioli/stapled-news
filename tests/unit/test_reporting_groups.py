from stapled.analyze.reporting_groups import build_reporting_groups


def test_exact_copies_collapse_but_provenance_and_owner_remain_visible():
    groups = build_reporting_groups(
        [
            {"article_id": "a2", "outlet": "B", "headline": "Wire report", "owner": "same"},
            {"article_id": "a1", "outlet": "A", "headline": " wire   report ", "owner": "same"},
            {"article_id": "a3", "outlet": "C", "headline": "Independent report", "owner": "other"},
        ]
    )
    assert [g.member_article_ids for g in groups] == [("a1", "a2"), ("a3",)]
    assert groups[0].method == "exact_headline"
    assert groups[0].owner == "same"


def test_demonstrated_lineage_collapses_and_owner_sensitivity_is_exposed():
    groups = build_reporting_groups([
        {"article_id": "a", "outlet": "A", "headline": "one", "lineage_id": "wire-1", "owner": "owner"},
        {"article_id": "b", "outlet": "B", "headline": "two", "lineage_id": "wire-1", "owner": "owner"},
    ])
    assert groups[0].method == "demonstrated_lineage"
    assert groups[0].lineage_evidence == "wire-1"
    assert groups[0].owner_sensitivity is True
