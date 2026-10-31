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
