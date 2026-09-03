import pytest

from cv_agent.agent.language import LanguagePolicy


@pytest.mark.parametrize(
    ("configured", "question", "expected"),
    [
        ("es", "Tell me about Python", "es"),
        ("en", "¿Qué experiencia tiene?", "en"),
        ("auto", "¿Qué experiencia tiene?", "es"),
        ("auto", "Tell me about Python", "en"),
    ],
)
def test_effective_language(configured, question, expected):
    assert LanguagePolicy(configured).effective_language(question) == expected


def test_spanish_setting_rejects_english_answer():
    policy = LanguagePolicy("es")
    assert policy.validate("The candidate uses Python. Sources: [[Python]]", "es") is False


def test_english_setting_rejects_spanish_answer():
    policy = LanguagePolicy("en")
    assert policy.validate("La persona usa Python. Fuentes: [[Python]]", "en") is False


def test_citation_titles_are_ignored_when_scoring_language():
    policy = LanguagePolicy("en")
    assert policy.validate("Python and APIs.\nSources: [[Experiencia profesional]]", "en") is True


def test_sources_label_and_fallback_are_localized():
    policy = LanguagePolicy("auto")
    assert policy.sources_label("en") == "Sources:"
    assert policy.sources_label("es") == "Fuentes:"
    assert policy.fallback("en", ["Python"]).endswith("Sources: [[Python]]")
    assert policy.fallback("es", ["Python"]).endswith("Fuentes: [[Python]]")


def test_policy_rejects_unknown_configuration():
    with pytest.raises(ValueError):
        LanguagePolicy("fr")


@pytest.mark.parametrize(
    "answer",
    [
        "Hola mundo\nFuentes: [[Python]]",
        "El candidato usa Python\nFuentes: [[Python]]",
        "Experiencia: Python\nFuentes: [[Python]]",
    ],
)
def test_spanish_accepts_normal_concise_answers(answer):
    assert LanguagePolicy("es").validate(answer, "es") is True


def test_spanish_rejects_english_accented_loanword_sentence():
    assert LanguagePolicy("es").validate("The résumé is strong\nFuentes: [[Python]]", "es") is False


def test_english_rejects_spanish_dominant_mixed_sentence():
    assert LanguagePolicy("en").validate("La persona has experiencia\nSources: [[Python]]", "en") is False


def test_bullet_content_is_scored_after_stripping_list_markers():
    policy = LanguagePolicy("es")
    assert policy.validate("- Experiencia con Python\n- Desarrollo de APIs\nFuentes: [[Python]]", "es") is True


def test_wrong_language_bullets_fail_even_with_valid_intro():
    policy = LanguagePolicy("es")
    assert policy.validate("Respuesta breve.\n- The candidate is strong\nFuentes: [[Python]]", "es") is False
