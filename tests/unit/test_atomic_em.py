from stapled.infer.atomic_em import fit_categorical, publication_gate


def test_em_masks_unknown_and_withholds_without_heldout_gate():
    model = fit_categorical([("source-a", "support", True), ("source-a", "unknown", False)], anchors={0: True})
    assert model["observations"] == 1
    assert publication_gate(.02, [.0, .01], heldout_adjudicated=79) == "withheld"


def test_publication_requires_superiority_and_all_controls_noninferior():
    assert publication_gate(.02, [.0, .01], heldout_adjudicated=80) == "published"
    assert publication_gate(0, [.0, -.01], heldout_adjudicated=80) == "withheld"
