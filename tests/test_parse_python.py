import hashlib

from graphdex.models import Confidence
from graphdex.parsing import SUPPORTED_EXTENSIONS, parse_file

SOURCE = b'''\
import os
import utils.helpers as helpers
from services.auth import login as do_login


class UserService:
    def get_user(self, user_id):
        do_login(user_id)
        return helpers.load(user_id)


def test_get_user():
    svc = UserService()
    svc.get_user(1)


def save(data):
    return os.path.join("x", data)
'''


def _parse():
    return parse_file("services/users.py", SOURCE, "python")


def test_extension_map():
    assert SUPPORTED_EXTENSIONS[".py"] == "python"


def test_content_hash():
    assert _parse().content_hash == hashlib.sha256(SOURCE).hexdigest()


def test_nodes_extracted():
    by_qn = {n.qualified_name: n for n in _parse().nodes}
    cls = by_qn["services/users.py::UserService"]
    assert cls.kind == "class"
    method = by_qn["services/users.py::UserService.get_user"]
    assert method.kind == "function"
    assert method.parent == "services/users.py::UserService"
    assert method.signature == "def get_user(self, user_id)"
    fn = by_qn["services/users.py::save"]
    assert fn.line_start > cls.line_end


def test_test_detection():
    by_qn = {n.qualified_name: n for n in _parse().nodes}
    assert by_qn["services/users.py::test_get_user"].is_test is True
    assert by_qn["services/users.py::save"].is_test is False


def test_imports_mapping():
    imports = _parse().imports
    assert imports["helpers"] == ("utils.helpers", "*")
    assert imports["do_login"] == ("services.auth", "login")
    assert imports["os"] == ("os", "*")


def test_calls_are_raw_name_only():
    calls = [e for e in _parse().edges if e.kind == "CALLS"]
    targets = {(e.src, e.dst) for e in calls}
    assert ("services/users.py::UserService.get_user", "do_login") in targets
    assert ("services/users.py::UserService.get_user", "helpers.load") in targets
    assert ("services/users.py::test_get_user", "UserService") in targets
    assert all(e.confidence is Confidence.NAME_ONLY for e in calls)


def test_contains_edges():
    contains = {(e.src, e.dst) for e in _parse().edges if e.kind == "CONTAINS"}
    assert ("services/users.py",
            "services/users.py::UserService") in contains
    assert ("services/users.py::UserService",
            "services/users.py::UserService.get_user") in contains


def test_unknown_language_raises():
    try:
        parse_file("x.zig", b"", "zig")
        raised = False
    except ValueError:
        raised = True
    assert raised
