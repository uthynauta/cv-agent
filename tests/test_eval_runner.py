import importlib.util
from pathlib import Path


_RUN_EVAL_PATH = Path(__file__).resolve().parents[1] / "evals" / "run_eval.py"
_SPEC = importlib.util.spec_from_file_location("run_eval", _RUN_EVAL_PATH)
assert _SPEC and _SPEC.loader
_RUN_EVAL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RUN_EVAL)


def test_eval_model_defaults_to_generic_agent(monkeypatch):
    monkeypatch.delenv("AGENT_MODEL_NAME", raising=False)

    assert _RUN_EVAL.resolve_model_name() == "cv-agent"


def test_eval_model_uses_configured_agent_model(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL_NAME", "deployment-model")

    assert _RUN_EVAL.resolve_model_name() == "deployment-model"
