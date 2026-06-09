"""Scoped bridge from boto3 credentials to AWS_* env vars for google-auth.

google-auth's AWS provider cannot read IMDSv2 metadata inside Docker
containers, while boto3 can. We briefly expose boto3's resolved credentials as
AWS_* env vars so google-auth (used by the BigQuery client's Workload Identity
Federation) skips the metadata service. The mutation is scoped to a context
manager so credentials never linger in the process environment past the BQ
load - these export CLIs run further steps afterward, and a long-lived
AWS_SESSION_TOKEN in os.environ is both a leak risk and a staleness bug.
"""
from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator

_AWS_ENV_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")


@contextlib.contextmanager
def bridge_boto3_credentials_to_env() -> Iterator[None]:
    """Temporarily set AWS_* env vars from boto3's resolved credentials.

    Restores the prior environment (including the absence of a key) on exit,
    even if the wrapped block raises. No-op when boto3 has no credentials.
    """
    import boto3

    saved = {key: os.environ.get(key) for key in _AWS_ENV_KEYS}
    try:
        creds = boto3.Session().get_credentials()
        if creds:
            frozen = creds.get_frozen_credentials()
            os.environ["AWS_ACCESS_KEY_ID"] = frozen.access_key
            os.environ["AWS_SECRET_ACCESS_KEY"] = frozen.secret_key
            if frozen.token:
                os.environ["AWS_SESSION_TOKEN"] = frozen.token
        yield
    finally:
        for key, prior in saved.items():
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior
