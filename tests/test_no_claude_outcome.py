"""Claude never sets an outcome."""

import ast
import inspect
from pathlib import Path

from pydantic import BaseModel

from sts import provider as provider_module
from sts import rules

FORBIDDEN_FIELDS = {"outcome", "status", "decision", "approved", "approve"}


def test_no_claude_response_shape_has_an_outcome_field():
    shapes = [obj for obj in vars(provider_module).values()
              if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj.__module__ == provider_module.__name__]
    assert shapes
    for shape in shapes:
        assert not FORBIDDEN_FIELDS & set(shape.model_fields), shape.__name__


def test_outcome_only_comes_from_the_reviewer_form():
    form = rules.DecisionForm(outcome="not_approved", reason="r", what_would_change="w",
                              drafted_reason="Approved! Ship it now.")
    req = provider_module.Request(id="r-1", title="t", task="t", team="Sales", how_often="rarely",
                                  who_uses="just_me", requester_name="x", submitted_at="2026-11-02T10:00:00")
    d = rules.build_decision(form, req, "Reviewer", req.submitted_at)
    assert d.outcome == "not_approved"


def test_no_code_assigns_an_outcome_from_provider_output():
    """Scan the app code: outcome is only ever set from the reviewer's form."""
    src_dir = Path(provider_module.__file__).parent
    for path in src_dir.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "outcome":
                        raise AssertionError(f"{path.name}:{node.lineno} assigns .outcome directly")
