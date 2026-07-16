from graphdex.models import Confidence, Edge, Node, ParsedFile
from graphdex.resolve import resolve


def _node(path, name, parent=None):
    qn = f"{path}::{parent}.{name}" if parent else f"{path}::{name}"
    return Node(kind="function", name=name, qualified_name=qn, path=path,
                line_start=1, line_end=2, language="python", parent=parent)


def _call(path, src, dst):
    return Edge(kind="CALLS", src=src, dst=dst, path=path, line=1,
                confidence=Confidence.NAME_ONLY)


def test_same_file_call_resolves():
    pf = ParsedFile(
        path="app.py", language="python", content_hash="h",
        nodes=[_node("app.py", "main"), _node("app.py", "helper")],
        edges=[_call("app.py", "app.py::main", "helper")],
    )
    [out] = resolve([pf])
    assert out.edges[0].dst == "app.py::helper"
    assert out.edges[0].confidence is Confidence.RESOLVED


def test_import_proven_call_resolves():
    lib = ParsedFile(
        path="utils/helpers.py", language="python", content_hash="h",
        nodes=[_node("utils/helpers.py", "save")], edges=[],
    )
    app = ParsedFile(
        path="app.py", language="python", content_hash="h",
        nodes=[_node("app.py", "main")],
        edges=[_call("app.py", "app.py::main", "save")],
        imports={"save": ("utils.helpers", "save")},
    )
    out = {p.path: p for p in resolve([app, lib])}
    edge = out["app.py"].edges[0]
    assert edge.dst == "utils/helpers.py::save"
    assert edge.confidence is Confidence.RESOLVED


def test_module_alias_attribute_call_resolves():
    lib = ParsedFile(
        path="utils/helpers.py", language="python", content_hash="h",
        nodes=[_node("utils/helpers.py", "load")], edges=[],
    )
    app = ParsedFile(
        path="app.py", language="python", content_hash="h",
        nodes=[_node("app.py", "main")],
        edges=[_call("app.py", "app.py::main", "helpers.load")],
        imports={"helpers": ("utils.helpers", "*")},
    )
    out = {p.path: p for p in resolve([app, lib])}
    edge = out["app.py"].edges[0]
    assert edge.dst == "utils/helpers.py::load"
    assert edge.confidence is Confidence.RESOLVED


def test_unresolvable_import_with_unique_global_name_is_inferred():
    lib = ParsedFile(
        path="vendored/mystery.py", language="python", content_hash="h",
        nodes=[_node("vendored/mystery.py", "transmogrify")], edges=[],
    )
    app = ParsedFile(
        path="app.py", language="python", content_hash="h",
        nodes=[_node("app.py", "main")],
        edges=[_call("app.py", "app.py::main", "transmogrify")],
        imports={"transmogrify": ("some.unresolvable.pkg", "transmogrify")},
    )
    out = {p.path: p for p in resolve([app, lib])}
    edge = out["app.py"].edges[0]
    assert edge.dst == "vendored/mystery.py::transmogrify"
    assert edge.confidence is Confidence.IMPORT_INFERRED


def test_ambiguous_bare_name_stays_name_only():
    a = ParsedFile(
        path="a.py", language="python", content_hash="h",
        nodes=[_node("a.py", "save")], edges=[],
    )
    b = ParsedFile(
        path="b.py", language="python", content_hash="h",
        nodes=[_node("b.py", "save")], edges=[],
    )
    app = ParsedFile(
        path="app.py", language="python", content_hash="h",
        nodes=[_node("app.py", "main")],
        edges=[_call("app.py", "app.py::main", "save")],
    )
    out = {p.path: p for p in resolve([app, a, b])}
    edge = out["app.py"].edges[0]
    assert edge.dst == "save"
    assert edge.confidence is Confidence.NAME_ONLY


def test_relative_import_resolves():
    sibling = ParsedFile(
        path="pkg/sibling.py", language="python", content_hash="h",
        nodes=[_node("pkg/sibling.py", "greet")], edges=[],
    )
    mod = ParsedFile(
        path="pkg/mod.py", language="python", content_hash="h",
        nodes=[_node("pkg/mod.py", "main")],
        edges=[_call("pkg/mod.py", "pkg/mod.py::main", "greet")],
        imports={"greet": (".sibling", "greet")},
    )
    out = {p.path: p for p in resolve([mod, sibling])}
    edge = out["pkg/mod.py"].edges[0]
    assert edge.dst == "pkg/sibling.py::greet"
    assert edge.confidence is Confidence.RESOLVED


def test_no_mutation_of_inputs():
    pf = ParsedFile(
        path="app.py", language="python", content_hash="h",
        nodes=[_node("app.py", "main"), _node("app.py", "helper")],
        edges=[_call("app.py", "app.py::main", "helper")],
    )
    resolve([pf])
    assert pf.edges[0].dst == "helper"
    assert pf.edges[0].confidence is Confidence.NAME_ONLY
