from __future__ import annotations

import importlib.resources as pkg_resources

from topogen.render import get_templates


def test_get_templates_lists_packaged_templates():
    templates = get_templates()
    assert "iosv" in templates
    assert "iol-xe" in templates
    assert "frr" in templates


def test_get_templates_suffix_strip(monkeypatch):
    class FakeResources:
        @staticmethod
        def files(_):
            class FakePackage:
                @staticmethod
                def iterdir():
                    return [
                        type("Resource", (), {"name": "a.jinja2"})(),
                        type("Resource", (), {"name": "b.txt"})(),
                        type("Resource", (), {"name": "c.jinja2"})(),
                    ]

            return FakePackage()

    monkeypatch.setattr(pkg_resources, "files", FakeResources.files)
    assert get_templates() == ["a", "c"]
