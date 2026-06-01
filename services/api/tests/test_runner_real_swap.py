"""Tests for the wizard child runner constructor/factory wiring.

What this file covers (allowlist-friendly, <100ms total):

  * The constructor parameter ``scene_search_client``.
  * Module-level integrity (imports, factory wiring).

What this file does NOT cover:

  * End-to-end run of ``_process_child_payload`` — that needs a
    real DB session + render service mock + opensearch fake. The
    fixture surface for a self-contained integration test exceeds
    the allowlist's <300ms budget. Per plan §9.4, the runner's
    full flow is verified on staging by manually triggering a
    wizard scan order and observing children land with
    ``render_job_id`` set on the parent's child rows. Adding the
    integration test post-PR #6 lands at the wizard-frontend tier
    (PR #7 brings tests against a real wizard surface anyway).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.modules.shorts_auto_product.children.runner import (
    ChildRunner,
    create_child_runner,
)


# ---------------------------------------------------------------------
# constructor wiring
# ---------------------------------------------------------------------


def _settings_stub():
    """Minimal settings stub — only the fields ChildRunner reads at
    construction. Avoids ``Settings()`` which requires env var
    plumbing."""
    s = MagicMock()
    s.auto_shorts_product_v2_child_runner_max_concurrency = 4
    s.auto_shorts_product_v2_child_runner_poll_seconds = 5
    s.auto_shorts_product_v2_child_runner_enabled = True
    s.auto_shorts_product_v2_child_lease_seconds = 300
    return s


def test_constructor_accepts_scene_search_client() -> None:
    """The PR #6 ctor change adds ``scene_search_client``. Verify
    the parameter is stored verbatim so the runner can hand it to
    :class:`ShortsRenderService` later."""
    fake_search = object()
    runner = ChildRunner(
        settings=_settings_stub(),
        session_factory=MagicMock(),
        scene_search_client=fake_search,
    )
    assert runner.scene_search_client is fake_search


def test_factory_threads_scene_search_client_through() -> None:
    """``create_child_runner`` is what ``app.main:lifespan`` calls.
    Verify it forwards the ctor arg unchanged so a future refactor
    of the factory's signature can't silently drop the OS client."""
    fake_search = object()
    runner = create_child_runner(
        settings=_settings_stub(),
        session_factory=MagicMock(),
        scene_search_client=fake_search,
    )
    assert runner.scene_search_client is fake_search


def test_constructor_default_process_fn_is_real_payload() -> None:
    """When tests don't inject ``process_child_fn``, production code
    runs. Asserting this here so a refactor that flips the default
    to a stub (which would tank prod) is caught at test time."""
    runner = ChildRunner(
        settings=_settings_stub(),
        session_factory=MagicMock(),
        scene_search_client=object(),
    )
    # Bound method comparison: __func__ pulls the underlying function
    # off both sides so we don't compare bound-method identity which
    # can vary across Python versions.
    assert runner._process_child_fn.__func__ is ChildRunner._process_child_payload

