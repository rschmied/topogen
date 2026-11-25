"""template discovery helpers."""

import importlib.resources as pkg_resources

from topogen import templates


def get_templates() -> list[str]:
    """get all available templates in the package"""
    return [
        resource.name[: -len(".jinja2")]
        for resource in pkg_resources.files(templates).iterdir()
        if resource.name.endswith(".jinja2")
    ]
