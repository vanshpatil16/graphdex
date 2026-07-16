from graphdex.subtokens import subtokenize


def test_camel_case_split():
    assert subtokenize("getUserById") == "get user by id"


def test_snake_case_split():
    assert subtokenize("parse_source_file") == "parse source file"


def test_acronym_handling():
    assert subtokenize("HTTPServerError") == "http server error"


def test_mixed_and_digits():
    assert subtokenize("load2FASecret_key") == "load2 fa secret key"


def test_empty_and_symbols():
    assert subtokenize("") == ""
    assert subtokenize("__init__") == "init"
