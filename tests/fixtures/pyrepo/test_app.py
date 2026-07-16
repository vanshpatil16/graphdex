from app import handle


def test_handle():
    assert handle(1) == {"saved": 1}
