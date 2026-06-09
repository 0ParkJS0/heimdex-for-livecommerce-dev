"""Tests for the scoped boto3 -> AWS_* env bridge used by the BQ exporters."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.cli._bq_env import bridge_boto3_credentials_to_env

_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")


def _fake_boto3_session(access="AK", secret="SK", token="TK"):
    frozen = MagicMock(access_key=access, secret_key=secret, token=token)
    creds = MagicMock()
    creds.get_frozen_credentials.return_value = frozen
    session = MagicMock()
    session.get_credentials.return_value = creds
    return session


@pytest.fixture(autouse=True)
def _clear_aws_env():
    saved = {k: os.environ.get(k) for k in _KEYS}
    for k in _KEYS:
        os.environ.pop(k, None)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class TestBridgeBoto3CredentialsToEnv:
    def test_sets_inside_then_restores_absent(self):
        with (
            patch("boto3.Session", return_value=_fake_boto3_session()),
            bridge_boto3_credentials_to_env(),
        ):
            assert os.environ["AWS_ACCESS_KEY_ID"] == "AK"
            assert os.environ["AWS_SECRET_ACCESS_KEY"] == "SK"
            assert os.environ["AWS_SESSION_TOKEN"] == "TK"
        # All keys were absent before -> must be absent after.
        for k in _KEYS:
            assert k not in os.environ

    def test_restores_prior_value(self):
        os.environ["AWS_ACCESS_KEY_ID"] = "PRIOR"
        with (
            patch("boto3.Session", return_value=_fake_boto3_session()),
            bridge_boto3_credentials_to_env(),
        ):
            assert os.environ["AWS_ACCESS_KEY_ID"] == "AK"
        assert os.environ["AWS_ACCESS_KEY_ID"] == "PRIOR"

    def test_restores_on_exception(self):
        with (
            patch("boto3.Session", return_value=_fake_boto3_session()),
            pytest.raises(RuntimeError),
            bridge_boto3_credentials_to_env(),
        ):
            raise RuntimeError("boom")
        for k in _KEYS:
            assert k not in os.environ

    def test_no_token_leaves_session_token_unset(self):
        with (
            patch("boto3.Session", return_value=_fake_boto3_session(token=None)),
            bridge_boto3_credentials_to_env(),
        ):
            assert os.environ["AWS_ACCESS_KEY_ID"] == "AK"
            assert "AWS_SESSION_TOKEN" not in os.environ

    def test_no_credentials_is_noop(self):
        session = MagicMock()
        session.get_credentials.return_value = None
        with (
            patch("boto3.Session", return_value=session),
            bridge_boto3_credentials_to_env(),
        ):
            for k in _KEYS:
                assert k not in os.environ
