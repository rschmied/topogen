"""template discovery helpers."""

import importlib.resources as pkg_resources

from topogen import templates


def get_templates() -> list[str]:
    """get all available templates in the package"""
    return [t[: -len(".jinja2")] for t in pkg_resources.contents(templates) if t.endswith(".jinja2")]
