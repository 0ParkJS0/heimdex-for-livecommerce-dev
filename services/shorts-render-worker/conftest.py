"""Root conftest — mock heimdex_worker_sdk so tests run outside Docker."""

import sys
from types import ModuleType
from unittest.mock import MagicMock

# heimdex_worker_sdk is pip-installed inside the Docker container but not
# available on the host dev machine. Register a lightweight stub so all
# ``from heimdex_worker_sdk import ...`` in worker source modules resolve
# without error. The stub is injected BEFORE any test collection.

_sdk_stub = ModuleType("heimdex_worker_sdk")
_sdk_stub.emit_event = MagicMock()  # type: ignore[attr-defined]

_sdk_s3 = ModuleType("heimdex_worker_sdk.s3")
_sdk_s3.S3Client = MagicMock()  # type: ignore[attr-defined]

_sdk_settings = ModuleType("heimdex_worker_sdk.settings")
_sdk_settings.get_worker_settings = MagicMock()  # type: ignore[attr-defined]

_sdk_internal_api = ModuleType("heimdex_worker_sdk.internal_api")
_sdk_internal_api.InternalAPIClient = MagicMock()  # type: ignore[attr-defined]

sys.modules.setdefault("heimdex_worker_sdk", _sdk_stub)
sys.modules.setdefault("heimdex_worker_sdk.s3", _sdk_s3)
sys.modules.setdefault("heimdex_worker_sdk.settings", _sdk_settings)
sys.modules.setdefault("heimdex_worker_sdk.internal_api", _sdk_internal_api)
