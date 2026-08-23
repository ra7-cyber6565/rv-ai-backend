"""Regression coverage for pytest 9.x fixture-definition objects.

The standalone pytest-style runner intentionally duck-types pytest fixtures so it
can also run in the zero-dependency sandbox.  Pytest 9 returns a
FixtureFunctionDefinition carrying ``_fixture_function_marker`` and
``_fixture_function`` instead of the legacy wrapper's
``_pytestfixturefunction`` marker.  These tests use that public-runtime shape
without depending on whichever pytest version happens to be installed.
"""
from __future__ import annotations

import importlib.util
import os
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER_PATH = os.path.join(ROOT, "tests", "run_pytest_style_suites.py")


def _load_runner():
    spec = importlib.util.spec_from_file_location("rv_runner_pytest9_probe", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


class _Marker:
    def __init__(self, *, name=None, scope="function", params=None, autouse=False):
        self.name = name
        self.scope = scope
        self.params = params
        self.autouse = autouse


class _Pytest9FixtureDefinition:
    """Minimal pytest 9 FixtureFunctionDefinition shape used by the runner."""

    def __init__(self, function, marker):
        self._fixture_function = function
        self._fixture_function_marker = marker
        self.__name__ = function.__name__
        self.__module__ = function.__module__

    def __call__(self, *args, **kwargs):
        raise RuntimeError("fixture definition must be unwrapped before direct call")


def _definition(function, *, name=None, scope="function", params=None,
                autouse=False):
    return _Pytest9FixtureDefinition(
        function,
        _Marker(name=name, scope=scope, params=params, autouse=autouse),
    )


def test_collect_fixtures_accepts_pytest9_definition_shape():
    def raw_value():
        return 41

    module = types.SimpleNamespace(value=_definition(raw_value, name="alias"))
    found = RUNNER._collect_fixtures(module)

    assert set(found) == {"alias"}
    assert found["alias"].func is raw_value
    assert found["alias"].scope == "function"
    assert found["alias"].autouse is False


def test_pytest9_shape_resolves_nested_named_and_autouse_fixtures():
    state = {"setup": 0, "teardown": 0}

    def base():
        return 41

    def bumped(base):
        return base + 1

    def isolated():
        state["setup"] += 1
        yield
        state["teardown"] += 1

    def test_body(answer):
        assert answer == 42

    module = types.SimpleNamespace(
        base=_definition(base),
        bumped=_definition(bumped, name="answer"),
        isolated=_definition(isolated, autouse=True),
    )
    session = RUNNER._FixtureSession(module)
    kwargs, cleanup, skip_reason = session.prepare(test_body)

    assert skip_reason == ""
    assert kwargs == {"answer": 42}
    assert state == {"setup": 1, "teardown": 0}
    test_body(**kwargs)
    assert RUNNER._teardown(cleanup) == []
    assert state == {"setup": 1, "teardown": 1}
    assert session.close() == []


def test_mutation_legacy_marker_only_loses_pytest9_fixture():
    """Mutation proof: old marker-only collector must demonstrably go red."""
    def raw_value():
        return 1

    fixture = _definition(raw_value, name="alias")
    original = RUNNER._fixture_marker
    RUNNER._fixture_marker = lambda obj: getattr(obj, "_pytestfixturefunction", None)
    try:
        found = RUNNER._collect_fixtures(types.SimpleNamespace(value=fixture))
    finally:
        RUNNER._fixture_marker = original

    assert "alias" not in found
