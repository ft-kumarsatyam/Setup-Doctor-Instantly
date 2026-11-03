"""Compat shim — prefer `setup_doctor.surfaces.api`."""
from setup_doctor.surfaces.api import *  # noqa: F403
from setup_doctor.surfaces.api import (  # noqa: F401
    DiagnoseRequest,
    DiagnoseResponse,
    _RateLimiter,
    _ResponseCache,
    app,
    create_app,
    validate_hostname,
)
