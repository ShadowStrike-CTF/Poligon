# Poligon — shared pytest config: hypothesis profiles for the property tests.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam

import os

from hypothesis import HealthCheck, settings

# Examples are per template × difficulty pair (tests/test_properties.py).
# Default run: ci. Deep run: pytest --hypothesis-profile=deep
_COMMON = dict(deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.register_profile("ci", max_examples=25, **_COMMON)
settings.register_profile("deep", max_examples=300, **_COMMON)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))


# F02: the apps only answer Host 127.0.0.1 / localhost (TrustedHostMiddleware).
# Starlette's TestClient defaults to Host "testserver", so point its default at
# loopback here instead of loosening the production allowlist. Runs at conftest
# import, before any test module builds a client.
from starlette.testclient import TestClient

_orig_init = TestClient.__init__


def _loopback_init(self, app, base_url="http://127.0.0.1", *args, **kwargs):
    _orig_init(self, app, base_url, *args, **kwargs)


TestClient.__init__ = _loopback_init
