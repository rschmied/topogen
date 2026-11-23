from __future__ import annotations

import importlib.resources as pkg_resources

from topogen.render import get_templates


def test_get_templates_lists_packaged_templates():
    templates = get_templates()
    assert "iosv" in templates
    assert "iol-xe" in templates
    assert "frr" in templates


def test_get_templates_suffix_strip(monkeypatch):
    class FakePkg:
        @staticmethod
        def contents(_):
            return ["a.jinja2", "b.txt", "c.jinja2"]

    monkeypatch.setattr(pkg_resources, "contents", FakePkg.contents)
    assert get_templates() == ["a", "c"]
