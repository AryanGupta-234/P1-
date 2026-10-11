from aie.model_policy import (
    DEFAULT_COMPLEX,
    DEFAULT_EMBEDDING,
    DEFAULT_ROUTINE,
    choose_local_model,
)


MODELS = {DEFAULT_ROUTINE, DEFAULT_COMPLEX, DEFAULT_EMBEDDING}


def test_routine_uses_installed_three_b_model():
    result = choose_local_model("routine", MODELS, available_memory_gib=2.0)
    assert result.selected_model == DEFAULT_ROUTINE
    assert result.available


def test_complex_falls_back_when_memory_is_low():
    result = choose_local_model("complex", MODELS, available_memory_gib=5.1)
    assert result.selected_model == DEFAULT_ROUTINE
    assert "memory guard" in result.reason.lower()


def test_complex_uses_seven_b_when_memory_is_sufficient():
    result = choose_local_model("complex", MODELS, available_memory_gib=9.0)
    assert result.selected_model == DEFAULT_COMPLEX


def test_embedding_uses_nomic_only():
    result = choose_local_model("embedding", MODELS, available_memory_gib=3.0)
    assert result.selected_model == DEFAULT_EMBEDDING


def test_missing_models_never_triggers_implicit_download():
    result = choose_local_model("routine", set(), available_memory_gib=12.0)
    assert result.selected_model is None
    assert not result.available


def test_routine_can_fall_back_to_installed_seven_b_with_memory():
    result = choose_local_model(
        "routine",
        {DEFAULT_COMPLEX},
        available_memory_gib=9.0,
    )
    assert result.selected_model == DEFAULT_COMPLEX
    assert "7B model" in result.reason


def test_routine_refuses_seven_b_fallback_under_memory_pressure():
    result = choose_local_model(
        "routine",
        {DEFAULT_COMPLEX},
        available_memory_gib=4.0,
    )
    assert result.selected_model is None
    assert not result.available
