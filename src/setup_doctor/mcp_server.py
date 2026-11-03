"""Compat shim — prefer `python -m setup_doctor.surfaces.mcp_server`."""
from setup_doctor.surfaces.mcp_server import *  # noqa: F403
from setup_doctor.surfaces.mcp_server import main  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
