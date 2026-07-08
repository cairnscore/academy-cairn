from academy_cairn.config import CairnConfig


def test_defaults():
    cfg = CairnConfig()
    assert cfg.base_url == "https://api.cairnscore.ai"
    assert cfg.default_weight == 0.3
    assert cfg.timeout_s == 5.0
    assert cfg.enabled is True
    assert cfg.offline is False
    assert cfg.flush_interval_s == 60.0
    assert cfg.namespace  # non-empty (hostname)
    assert cfg.key_dir.name == "keys"


def test_env_override(monkeypatch):
    monkeypatch.setenv("CAIRN_NAMESPACE", "argus")
    monkeypatch.setenv("CAIRN_OFFLINE", "1")
    monkeypatch.setenv("CAIRN_DEFAULT_WEIGHT", "0.5")
    cfg = CairnConfig()
    assert cfg.namespace == "argus"
    assert cfg.offline is True
    assert cfg.default_weight == 0.5
