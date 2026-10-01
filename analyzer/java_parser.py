"""tree-sitter-java front end: one pass per file, producing plain facts (no scoring)."""

from __future__ import annotations

from dataclasses import dataclass, field

import tree_sitter_java
from tree_sitter import Language, Node, Parser

_PARSER = Parser(Language(tree_sitter_java.language()))
_COMMENTS = {"line_comment", "block_comment"}
_TYPE_DECLS = {
    "class_declaration", "interface_declaration", "enum_declaration",
    "record_declaration", "annotation_type_declaration",
}
_BODIES = {"method_declaration", "constructor_declaration", "compact_constructor_declaration"}
_DECISIONS = {
    "if_statement", "for_statement", "enhanced_for_statement", "while_statement",
    "do_statement", "catch_clause", "ternary_expression",
}
_ANNOTATIONS = {"marker_annotation", "annotation"}


@dataclass(frozen=True)
class ImportRef:
    name: str  # as written, without a trailing ".*"
    line: int
    static: bool
    wildcard: bool


@dataclass(frozen=True)
class CallSite:
    receiver: str | None  # simple name of the object, None for unqualified or chained calls
    method: str
    line: int


@dataclass
class ParsedJava:
    package: str = ""
    top_level_types: list[str] = field(default_factory=list)
    type_lines: dict[str, int] = field(default_factory=dict)
    imports: list[ImportRef] = field(default_factory=list)
    identifiers: set[str] = field(default_factory=set)  # names used in code, imports excluded
    method_names: set[str] = field(default_factory=set)
    calls: list[CallSite] = field(default_factory=list)
    code_lines: set[int] = field(default_factory=set)
    bodies: int = 0
    decisions: int = 0
    test_methods: int = 0
    has_error: bool = False

    @property
    def loc(self) -> int:
        return len(self.code_lines)

    @property
    def complexity(self) -> int:
        return self.bodies + self.decisions


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8") if node is not None and node.text else ""


def _receiver(obj: Node | None) -> str | None:
    if obj is None:
        return None
    if obj.type == "identifier":
        return _text(obj)
    if obj.type == "field_access":  # this.delegator, a.b.Delegator
        return _text(obj.child_by_field_name("field"))
    return None


def _import(node: Node) -> ImportRef:
    name = next((_text(c) for c in node.children if c.type in ("scoped_identifier", "identifier")), "")
    kinds = [c.type for c in node.children]
    return ImportRef(name, node.start_point[0] + 1, "static" in kinds, "asterisk" in kinds)


def _is_decision(node: Node) -> bool:
    if node.type in _DECISIONS:
        return True
    if node.type == "switch_label":  # `case ...` counts, `default` does not
        return bool(node.children) and node.children[0].type == "case"
    if node.type == "binary_expression":
        return _text(node.child_by_field_name("operator")) in ("&&", "||")
    return False


def _count(node: Node, out: ParsedJava) -> None:
    if node.type in _BODIES and node.child_by_field_name("body") is not None:
        out.bodies += 1
    if _is_decision(node):
        out.decisions += 1
    if node.type == "method_declaration":
        out.method_names.add(_text(node.child_by_field_name("name")))
    if node.type in _ANNOTATIONS and _text(node.child_by_field_name("name")) == "Test":
        out.test_methods += 1
    if node.type == "method_invocation":
        name = node.child_by_field_name("name")
        out.calls.append(CallSite(_receiver(node.child_by_field_name("object")), _text(name),
                                  (name or node).start_point[0] + 1))


def parse_java(source: bytes) -> ParsedJava:
    tree = _PARSER.parse(source)
    out = ParsedJava(has_error=tree.root_node.has_error)
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in _COMMENTS:
            continue
        if node.type == "package_declaration":
            out.package = next((_text(c) for c in node.children if c.type == "scoped_identifier"
                                or c.type == "identifier"), "")
            out.code_lines.update(range(node.start_point[0] + 1, node.end_point[0] + 2))
            continue
        if node.type == "import_declaration":
            out.imports.append(_import(node))
            out.code_lines.update(range(node.start_point[0] + 1, node.end_point[0] + 2))
            continue
        if node.type in _TYPE_DECLS and node.parent is not None and node.parent.type == "program":
            type_name = _text(node.child_by_field_name("name"))
            out.top_level_types.append(type_name)
            out.type_lines[type_name] = node.start_point[0] + 1
        _count(node, out)
        if node.type in ("identifier", "type_identifier"):
            out.identifiers.add(_text(node))
        if node.child_count == 0:
            out.code_lines.update(range(node.start_point[0] + 1, node.end_point[0] + 2))
        stack.extend(reversed(node.children))
    return out
