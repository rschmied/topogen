from __future__ import annotations

import argparse
import importlib

import pytest

mainmod = importlib.import_module("topogen.main")


def test_valid_node_count():
    assert mainmod.valid_node_count("2") == 2
    assert mainmod.valid_node_count("1000") == 1000


@pytest.mark.parametrize("value", ["1", "1001"])
def test_valid_node_count_rejects_bad_values(value: str):
    with pytest.raises(argparse.ArgumentTypeError):
        mainmod.valid_node_count(value)


def test_get_log_level_known_and_unknown():
    level, unknown = mainmod.get_log_level("info")
    assert level == mainmod.logging.INFO
    assert unknown is False
    level, unknown = mainmod.get_log_level("bogus")
    assert level == mainmod.logging.WARNING
    assert unknown is True


def test_main_yaml_mode_writes_output(monkeypatch, tmp_path):
    out = tmp_path / "x.yaml"
    cfg = tmp_path / "config.toml"
    cfg.write_text("")
    called = {}
    monkeypatch.setattr(mainmod, "setup_logging", lambda *_: None)
    monkeypatch.setattr(
        mainmod.topogen.Config, "load", classmethod(lambda cls, _: cls())
    )
    monkeypatch.setattr(
        mainmod,
        "offline_main",
        lambda args: (
            called.setdefault("mode", args.mode),
            out.write_text(args.mode),
            0,
        )[2],
    )
    monkeypatch.setattr(
        mainmod.sys,
        "argv",
        [
            "topogen",
            "--config",
            str(cfg),
            "--output",
            str(out),
            "--mode",
            "simple",
            "2",
        ],
    )
    assert mainmod.main() == 0
    assert called["mode"] == "simple"


def test_main_list_templates(monkeypatch, capsys):
    monkeypatch.setattr(mainmod, "setup_logging", lambda *_: None)
    monkeypatch.setattr(
        mainmod.topogen.Config, "load", classmethod(lambda cls, _: cls())
    )
    monkeypatch.setattr(mainmod, "get_templates", lambda: ["iosv", "frr"])
    monkeypatch.setattr(mainmod.sys, "argv", ["topogen", "--list-templates"])
    assert mainmod.main() == 0
    assert "iosv" in capsys.readouterr().out


def test_main_write_config(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(mainmod, "setup_logging", lambda *_: None)
    monkeypatch.setattr(
        mainmod.topogen.Config, "load", classmethod(lambda cls, _: cls())
    )
    monkeypatch.setattr(mainmod.sys, "argv", ["topogen", "-w", "-c", str(path), "2"])
    assert mainmod.main() == 0


def test_create_argparser_defaults():
    parser = mainmod.create_argparser()
    args = parser.parse_args(["2"])
    assert args.output == "topogen_lab.yaml"
    assert args.nodes == 2
    assert args.mode == "nx"


def test_create_argparser_mode_and_template_defaults():
    parser = mainmod.create_argparser()
    args = parser.parse_args(["2"])
    assert args.template == "iosv"
    assert not hasattr(args, "cafile")
    assert not hasattr(args, "insecure")


def test_main_invalid_nodes(monkeypatch):
    monkeypatch.setattr(mainmod.sys, "argv", ["topogen", "abc"])
    with pytest.raises(ValueError):
        mainmod.valid_node_count("abc")


def test_setup_logging_warns_for_unknown_level(caplog):
    with caplog.at_level(mainmod.logging.WARNING):
        mainmod.setup_logging("invalid")
    assert "Unknown log level: INVALID" in caplog.messages


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["topogen"], "required: nodes"),
        (["topogen", "2", "--template", "unknown"], "unsupported template"),
    ],
)
def test_main_rejects_missing_nodes_and_unknown_template(
    monkeypatch, capsys, argv, message
):
    monkeypatch.setattr(mainmod, "setup_logging", lambda *_: None)
    monkeypatch.setattr(mainmod.sys, "argv", argv)
    monkeypatch.setattr(
        mainmod.topogen.Config, "load", classmethod(lambda cls, _: cls())
    )
    with pytest.raises(SystemExit):
        mainmod.main()
    assert message in capsys.readouterr().err
