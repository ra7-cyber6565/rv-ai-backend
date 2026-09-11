from research_engine.key_pool import KeyPool, describe, load_keys


def test_primary_scalar_keeps_normal_single_key_unchanged():
    env = {"GEMINI_API_KEY": "key-one"}
    assert load_keys(env) == ["key-one"]
    pool = KeyPool(load_keys(env))
    assert pool.active() == "key-one"
    assert pool.count == 1


def test_primary_scalar_safely_splits_accidental_multiline_secret():
    env = {"GEMINI_API_KEY": "key-one\nkey-two\r\nkey-three"}
    assert load_keys(env) == ["key-one", "key-two", "key-three"]
    info = describe(env)
    assert info["names_present"] == ["GEMINI_API_KEY"]
    assert info["unique_keys"] == 3
    assert info["backup_slots"] == 2


def test_primary_scalar_safely_splits_comma_and_semicolon_secret():
    env = {"GEMINI_API_KEY": "key-one,key-two;key-three"}
    assert load_keys(env) == ["key-one", "key-two", "key-three"]


def test_numbered_backup_and_list_variables_share_same_normalization_and_dedupe():
    env = {
        "GEMINI_API_KEY": "key-one,key-two",
        "GEMINI_API_KEY_2": "key-two\nkey-three",
        "GEMINI_API_KEY_BACKUP": "key-four;key-five",
        "GEMINI_API_KEYS": "key-five key-six",
    }
    assert load_keys(env) == [
        "key-one", "key-two", "key-three", "key-four", "key-five", "key-six"
    ]
    info = describe(env)
    assert info["unique_keys"] == 6
    assert info["duplicates_dropped"] == 2
    assert info["backup_slots"] == 5


def test_whitespace_only_and_empty_slots_are_ignored():
    env = {
        "GEMINI_API_KEY": " \n\t ",
        "GEMINI_API_KEY_BACKUP": " key-one \n ",
        "GEMINI_API_KEY_LIST": ", ; \n key-two \t",
    }
    assert load_keys(env) == ["key-one", "key-two"]
