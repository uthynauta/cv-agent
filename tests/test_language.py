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
