from graphdex.models import Confidence, Edge, Node, ParsedFile


def test_confidence_ordering():
    assert Confidence.NAME_ONLY < Confidence.IMPORT_INFERRED < Confidence.RESOLVED
    assert int(Confidence.NAME_ONLY) == 0
    assert int(Confidence.RESOLVED) == 2


def test_node_is_frozen_with_defaults():
    node = Node(
        kind="function", name="save", qualified_name="utils/helpers.py::save",
        path="utils/helpers.py", line_start=3, line_end=9, language="python",
    )
    assert node.parent is None
    assert node.signature is None
    assert node.is_test is False
    try:
        node.name = "other"
        raised = False
    except AttributeError:
        raised = True
    assert raised


def test_edge_default_confidence_is_resolved():
    edge = Edge(kind="CALLS", src="a.py::f", dst="b.py::g", path="a.py", line=4)
    assert edge.confidence is Confidence.RESOLVED


def test_parsed_file_holds_imports_mapping():
    pf = ParsedFile(
        path="app.py", language="python", content_hash="abc",
        nodes=[], edges=[], imports={"save": ("utils.helpers", "save")},
    )
    assert pf.imports["save"] == ("utils.helpers", "save")
