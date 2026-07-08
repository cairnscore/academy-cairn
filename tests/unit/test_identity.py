import stat

from academy_cairn.identity import (
    KeyStore,
    agent_name_from,
    identity_slug,
    reviewer_external_id,
)


def test_reviewer_external_id():
    assert reviewer_external_id("argus", "triage") == "agent://academy/argus/triage"


def test_agent_name_fallback():
    assert agent_name_from("triage", "abcd1234ffff") == "triage"
    assert agent_name_from(None, "abcd1234ffff") == "anon-abcd1234"


def test_identity_slug():
    assert identity_slug("agent://academy/argus/triage") == "academy_argus_triage"


def test_keystore_roundtrip_and_perms(tmp_path):
    store = KeyStore(tmp_path, host="node01")
    assert store.load("academy_argus_triage") is None
    store.save("academy_argus_triage", "tg_secret")
    assert store.load("academy_argus_triage") == "tg_secret"
    key_file = tmp_path / "node01" / "academy_argus_triage.key"
    mode = stat.S_IMODE(key_file.stat().st_mode)
    assert mode == 0o600
