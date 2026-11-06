from __future__ import annotations


def test_a_sign_in_another_program_kept_is_stored_as_it_is(monkeypatch):
    import keyring

    from sources import get_source

    stored: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "set_password", lambda service, key, value: stored.__setitem__((service, key), value))

    get_source("dailywire").import_sign_in({"tokens": '{"access_token": "a"}'})

    assert stored == {("vodloft-dailywire-auth", "tokens"): '{"access_token": "a"}'}
