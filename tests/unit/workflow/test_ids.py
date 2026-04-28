from mobius.workflow.ids import readable_session_id, slugify


def test_slugify_keeps_meaningful_words_and_limits_length() -> None:
    assert slugify("Rendre Mobius efficace pour les agents à 100%") == (
        "rendre-mobius-efficace-pour-les"
    )


def test_slugify_handles_symbol_only_labels() -> None:
    assert slugify("!!!") == ""


def test_readable_session_id_uses_prefix_slug_and_unique_suffix() -> None:
    session_id = readable_session_id("run", "Fix every workflow crash")

    assert session_id.startswith("run_fix-every-workflow-crash_")
    assert len(session_id.rsplit("_", 1)[1]) == 8
