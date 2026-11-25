from __future__ import annotations

from topogen.config import Config


def test_config_defaults_are_independent():
    a = Config()
    b = Config()
    assert a.loopbacks == b.loopbacks
    assert a.p2pnets == b.p2pnets
    assert a is not b


def test_config_save_load_round_trip(tmp_path):
    cfg = Config(domainname="lab.local", username="alice", password="secret")
    path = tmp_path / "config.toml"
    cfg.save(str(path))
    loaded = Config.load(str(path))
    assert loaded.domainname == "lab.local"
    assert loaded.username == "alice"
    assert loaded.password == "secret"


def test_config_load_missing_file_uses_defaults(tmp_path):
    loaded = Config.load(str(tmp_path / "missing.toml"))
    assert loaded.domainname == "virl.lab"


def test_config_save_writes_file(tmp_path):
    cfg = Config()
    path = tmp_path / "config.toml"
    cfg.save(str(path))
    assert path.exists()
    assert "loopbacks" in path.read_text()
