"""Python extraction via tree-sitter. Produces raw (unresolved) CALLS edges;
resolution is a separate pass (graphdex.resolve)."""

from __future__ import annotations

import hashlib

from tree_sitter_language_pack import get_parser

from ..models import Confidence, Edge, Node, ParsedFile

_TEST_FILE_PREFIXES = ("test_",)
_TEST_FILE_SUFFIXES = ("_test.py",)


def _text(ts_node) -> str:
    return ts_node.text.decode("utf-8", errors="replace")


def _is_test_file(path: str) -> bool:
    basename = path.rsplit("/", 1)[-1]
    return basename.startswith(_TEST_FILE_PREFIXES) or basename.endswith(
        _TEST_FILE_SUFFIXES
    )


class PythonParser:
    language = "python"

    def parse(self, path: str, source: bytes) -> ParsedFile:
        parser = get_parser("python")
        tree = parser.parse(source)
        nodes: list[Node] = []
        edges: list[Edge] = []
        imports: dict[str, tuple[str, str]] = {}
        test_file = _is_test_file(path)

        root_line_end = tree.root_node.end_point[0] + 1
        nodes.append(Node(
            kind="file", name=path.rsplit("/", 1)[-1], qualified_name=path,
            path=path, line_start=1, line_end=root_line_end,
            language=self.language,
        ))

        self._walk(tree.root_node, path, None, None, nodes, edges,
                   imports, test_file)
        return ParsedFile(
            path=path, language=self.language,
            content_hash=hashlib.sha256(source).hexdigest(),
            nodes=nodes, edges=edges, imports=imports,
        )

    # -- traversal -------------------------------------------------------

    def _walk(self, ts_node, path: str, enclosing_class: str | None,
              enclosing_func: str | None, nodes: list[Node],
              edges: list[Edge], imports: dict[str, tuple[str, str]],
              test_file: bool) -> None:
        for child in ts_node.children:
            if child.type == "decorated_definition":
                inner = child.child_by_field_name("definition")
                if inner is not None:
                    self._walk_one(inner, path, enclosing_class,
                                   enclosing_func, nodes, edges, imports,
                                   test_file)
                continue
            self._walk_one(child, path, enclosing_class, enclosing_func,
                           nodes, edges, imports, test_file)

    def _walk_one(self, child, path: str, enclosing_class: str | None,
                  enclosing_func: str | None, nodes: list[Node],
                  edges: list[Edge], imports: dict[str, tuple[str, str]],
                  test_file: bool) -> None:
        kind = child.type
        if kind == "class_definition":
            self._handle_class(child, path, nodes, edges, imports, test_file)
        elif kind == "function_definition":
            self._handle_function(child, path, enclosing_class, nodes,
                                  edges, imports, test_file)
        elif kind == "import_statement":
            self._handle_import(child, path, edges, imports)
        elif kind == "import_from_statement":
            self._handle_import_from(child, path, edges, imports)
        elif kind == "call":
            self._handle_call(child, path, enclosing_class, enclosing_func,
                              edges)
            self._walk(child, path, enclosing_class, enclosing_func, nodes,
                       edges, imports, test_file)
        else:
            self._walk(child, path, enclosing_class, enclosing_func, nodes,
                       edges, imports, test_file)

    # -- handlers ----------------------------------------------------------

    def _handle_class(self, ts_node, path: str, nodes: list[Node],
                      edges: list[Edge], imports, test_file: bool) -> None:
        name_node = ts_node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node)
        qn = f"{path}::{name}"
        nodes.append(Node(
            kind="class", name=name, qualified_name=qn, path=path,
            line_start=ts_node.start_point[0] + 1,
            line_end=ts_node.end_point[0] + 1,
            language=self.language, signature=f"class {name}",
        ))
        edges.append(Edge(kind="CONTAINS", src=path, dst=qn, path=path,
                          line=ts_node.start_point[0] + 1))
        supers = ts_node.child_by_field_name("superclasses")
        if supers is not None:
            for arg in supers.children:
                if arg.type in ("identifier", "attribute"):
                    edges.append(Edge(
                        kind="INHERITS", src=qn, dst=_text(arg), path=path,
                        line=arg.start_point[0] + 1,
                        confidence=Confidence.NAME_ONLY,
                    ))
        body = ts_node.child_by_field_name("body")
        if body is not None:
            self._walk(body, path, qn, None, nodes, edges, imports,
                       test_file)

    def _handle_function(self, ts_node, path: str,
                         enclosing_class: str | None, nodes: list[Node],
                         edges: list[Edge], imports,
                         test_file: bool) -> None:
        name_node = ts_node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node)
        if enclosing_class:
            class_path, class_name = enclosing_class.rsplit("::", 1)
            qn = f"{class_path}::{class_name}.{name}"
        else:
            qn = f"{path}::{name}"
        params_node = ts_node.child_by_field_name("parameters")
        params = _text(params_node).strip("()") if params_node else ""
        nodes.append(Node(
            kind="function", name=name, qualified_name=qn, path=path,
            line_start=ts_node.start_point[0] + 1,
            line_end=ts_node.end_point[0] + 1,
            language=self.language,
            parent=enclosing_class,
            signature=f"def {name}({params})",
            is_test=test_file or name.startswith("test"),
        ))
        edges.append(Edge(kind="CONTAINS", src=enclosing_class or path,
                          dst=qn, path=path,
                          line=ts_node.start_point[0] + 1))
        body = ts_node.child_by_field_name("body")
        if body is not None:
            self._walk(body, path, enclosing_class, qn, nodes, edges,
                       imports, test_file)

    def _handle_import(self, ts_node, path: str, edges: list[Edge],
                       imports: dict[str, tuple[str, str]]) -> None:
        for child in ts_node.children:
            if child.type == "dotted_name":
                module = _text(child)
                local = module.split(".", 1)[0]
                imports[local] = (module, "*")
                self._import_edge(edges, path, module, child)
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node is None or alias_node is None:
                    continue
                module = _text(name_node)
                imports[_text(alias_node)] = (module, "*")
                self._import_edge(edges, path, module, child)

    def _handle_import_from(self, ts_node, path: str, edges: list[Edge],
                            imports: dict[str, tuple[str, str]]) -> None:
        module_node = ts_node.child_by_field_name("module_name")
        if module_node is None:
            return
        module = _text(module_node)
        self._import_edge(edges, path, module, ts_node)
        seen_import_kw = False
        for child in ts_node.children:
            if child.type == "import":
                seen_import_kw = True
                continue
            if not seen_import_kw:
                continue
            if child.type == "dotted_name":
                original = _text(child)
                imports[original] = (module, original)
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node is None or alias_node is None:
                    continue
                imports[_text(alias_node)] = (module, _text(name_node))

    def _handle_call(self, ts_node, path: str,
                     enclosing_class: str | None,
                     enclosing_func: str | None,
                     edges: list[Edge]) -> None:
        fn = ts_node.child_by_field_name("function")
        if fn is None:
            return
        if fn.type == "identifier":
            target = _text(fn)
        elif fn.type == "attribute":
            target = _text(fn)
            if target.count(".") > 2:
                return  # deep chains like a.b.c.d() — skip, low value
        else:
            return
        src = enclosing_func or enclosing_class or path
        edges.append(Edge(
            kind="CALLS", src=src, dst=target, path=path,
            line=ts_node.start_point[0] + 1,
            confidence=Confidence.NAME_ONLY,
        ))

    @staticmethod
    def _import_edge(edges: list[Edge], path: str, module: str,
                     ts_node) -> None:
        edges.append(Edge(
            kind="IMPORTS_FROM", src=path, dst=module, path=path,
            line=ts_node.start_point[0] + 1,
        ))
