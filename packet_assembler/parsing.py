"""YAML ingestion.

Reads a component definition file of the form::

    component:
      id: C-007
      name: Sentinel Request Gateway
      release: Release1-MVP
      ...

and returns the inner ``component`` mapping as a plain Python dict.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class IngestionError(Exception):
    """Raised when the YAML file cannot be read or is structurally invalid."""


def load_component(path: Path) -> dict[str, Any]:
    """Load and validate the structural shape of a component YAML file.

    We deliberately keep this to *structural* validation only (is it a file we
    can parse, is there a ``component`` mapping). Field-level rules live in the
    policy gate so that all business rules are in one auditable place.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise IngestionError(f"Cannot read input file '{path}': {exc}") from exc

    try:
        document = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise IngestionError(f"Input file '{path}' is not valid YAML: {exc}") from exc

    if not isinstance(document, dict) or "component" not in document:
        raise IngestionError(
            "Input YAML must contain a top-level 'component' mapping."
        )

    component = document["component"]
    if not isinstance(component, dict):
        raise IngestionError("'component' must be a mapping of fields.")

    return component
