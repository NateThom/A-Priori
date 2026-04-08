"""Tests for the Python Language Parser (Story 3.3, ERD §3.3.1).

Each test is directly traceable to an acceptance criterion:
- AC1: Top-level functions extracted with name, parameters, return annotation, line range
- AC2: Classes extracted with name, base classes, methods; inherits relationships identified
- AC3: from-import creates import relationship
- AC4: bare-import creates import relationship
- AC5: attribute call creates a calls relationship
- AC6: decorated function is still extracted correctly
- AC7: async function extracted identically to synchronous function
"""

from pathlib import Path

import pytest

from apriori.structural.languages.python_parser import PythonParser
from apriori.structural.models import ParseResult


@pytest.fixture
def parser() -> PythonParser:
    return PythonParser()


# ---------------------------------------------------------------------------
# AC1: Top-level functions extracted
# ---------------------------------------------------------------------------


def test_top_level_function_extracted(parser: PythonParser, tmp_path: Path) -> None:
    """Given a Python file with a top-level function, when parsed, then the function
    is extracted with name, parameters, return type annotation, line range, file path."""
    source = b"def greet(name: str, age: int) -> str:\n    return f'Hello {name}'\n"
    fp = tmp_path / "greet.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    assert len(result.functions) == 1
    func = result.functions[0]
    assert func.name == "greet"
    assert len(func.params) == 2
    assert func.params[0].name == "name"
    assert func.params[0].type_annotation == "str"
    assert func.params[1].name == "age"
    assert func.params[1].type_annotation == "int"
    assert func.return_type == "str"
    assert func.start_line == 1
    assert func.end_line >= 2
    assert func.file_path == fp


def test_function_without_type_annotations(parser: PythonParser, tmp_path: Path) -> None:
    """Given a function with no type annotations, then annotations are None."""
    source = b"def add(x, y):\n    return x + y\n"
    fp = tmp_path / "add.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    assert len(result.functions) == 1
    func = result.functions[0]
    assert func.name == "add"
    assert func.params[0].type_annotation is None
    assert func.params[1].type_annotation is None
    assert func.return_type is None


def test_multiple_top_level_functions(parser: PythonParser, tmp_path: Path) -> None:
    """Given multiple top-level functions, all are extracted."""
    source = b"def foo():\n    pass\n\ndef bar(x: int) -> bool:\n    return x > 0\n"
    fp = tmp_path / "multi.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    names = [f.name for f in result.functions]
    assert "foo" in names
    assert "bar" in names


# ---------------------------------------------------------------------------
# AC2: Classes extracted with base classes, methods, and inherits relationships
# ---------------------------------------------------------------------------


def test_class_extracted_with_name_and_base_classes(
    parser: PythonParser, tmp_path: Path
) -> None:
    """Given a class with base classes, when parsed, then class name, base classes,
    and methods are extracted and an inherits relationship is identified."""
    source = b"class Dog(Animal, Mixin):\n    def bark(self):\n        pass\n"
    fp = tmp_path / "dog.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    assert len(result.classes) == 1
    cls = result.classes[0]
    assert cls.name == "Dog"
    assert "Animal" in cls.bases
    assert "Mixin" in cls.bases
    assert len(cls.methods) == 1
    assert cls.methods[0].name == "bark"
    assert cls.file_path == fp

    inherits = [r for r in result.relationships if r.kind == "inherits"]
    assert len(inherits) == 2
    targets = {r.target for r in inherits}
    assert "Animal" in targets
    assert "Mixin" in targets
    sources = {r.source for r in inherits}
    assert all(s == "Dog" for s in sources)


def test_class_without_base_classes(parser: PythonParser, tmp_path: Path) -> None:
    """Given a class with no base classes, base_classes is empty and no inherits
    relationships are recorded."""
    source = b"class Standalone:\n    def method(self):\n        pass\n"
    fp = tmp_path / "standalone.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    assert len(result.classes) == 1
    cls = result.classes[0]
    assert cls.bases == []
    inherits = [r for r in result.relationships if r.kind == "inherits"]
    assert len(inherits) == 0


def test_class_methods_not_in_top_level_functions(
    parser: PythonParser, tmp_path: Path
) -> None:
    """Methods defined inside a class are not duplicated in result.functions."""
    source = b"class Foo:\n    def method(self):\n        pass\n\ndef standalone():\n    pass\n"
    fp = tmp_path / "mixed.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    top_level_names = [f.name for f in result.functions]
    assert "standalone" in top_level_names
    assert "method" not in top_level_names


# ---------------------------------------------------------------------------
# AC3: from-import creates import relationship
# ---------------------------------------------------------------------------


def test_from_import_relationship_recorded(
    parser: PythonParser, tmp_path: Path
) -> None:
    """Given `from module import func`, when parsed, then an import relationship
    is recorded with the module name and the imported name."""
    source = b"from os.path import join, exists\n"
    fp = tmp_path / "imports.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    imports = [r for r in result.relationships if r.kind == "imports"]
    assert len(imports) == 2
    targets = {r.target for r in imports}
    assert "join" in targets
    assert "exists" in targets
    sources = {r.source for r in imports}
    assert all(s == "os.path" for s in sources)


def test_from_import_single_name(parser: PythonParser, tmp_path: Path) -> None:
    """Given `from module import func`, when parsed, a single import relationship
    is recorded."""
    source = b"from pathlib import Path\n"
    fp = tmp_path / "pathlib_import.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    imports = [r for r in result.relationships if r.kind == "imports"]
    assert len(imports) == 1
    assert imports[0].source == "pathlib"
    assert imports[0].target == "Path"


# ---------------------------------------------------------------------------
# AC4: bare-import creates import relationship
# ---------------------------------------------------------------------------


def test_bare_import_relationship_recorded(
    parser: PythonParser, tmp_path: Path
) -> None:
    """Given `import module`, when parsed, then an import relationship is recorded
    with the full module name as target."""
    source = b"import os\nimport sys\n"
    fp = tmp_path / "bare_imports.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    imports = [r for r in result.relationships if r.kind == "imports"]
    targets = {r.target for r in imports}
    assert "os" in targets
    assert "sys" in targets


def test_bare_import_dotted_module(parser: PythonParser, tmp_path: Path) -> None:
    """Given `import os.path`, when parsed, the full dotted name is recorded."""
    source = b"import os.path\n"
    fp = tmp_path / "dotted.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    imports = [r for r in result.relationships if r.kind == "imports"]
    assert len(imports) == 1
    assert imports[0].target == "os.path"


# ---------------------------------------------------------------------------
# AC5: attribute call creates a calls relationship
# ---------------------------------------------------------------------------


def test_attribute_call_creates_calls_relationship(
    parser: PythonParser, tmp_path: Path
) -> None:
    """Given a function that calls `other_module.some_function()`, when parsed,
    then a calls relationship is identified."""
    source = b"def do_work():\n    other_module.some_function()\n"
    fp = tmp_path / "calls.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    calls = [r for r in result.relationships if r.kind == "calls"]
    assert len(calls) >= 1
    call_targets = {r.target for r in calls}
    assert "other_module.some_function" in call_targets


# ---------------------------------------------------------------------------
# AC6: Decorated function extracted correctly
# ---------------------------------------------------------------------------


def test_decorated_function_extracted(parser: PythonParser, tmp_path: Path) -> None:
    """Given a decorated function, when parsed, then the function is still
    extracted correctly with its name and parameters."""
    source = b"@property\ndef value(self) -> int:\n    return self._value\n"
    fp = tmp_path / "decorated.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    assert len(result.functions) == 1
    func = result.functions[0]
    assert func.name == "value"
    assert func.return_type == "int"


def test_multiple_decorators_function_extracted(
    parser: PythonParser, tmp_path: Path
) -> None:
    """Given a function with multiple decorators, it is extracted correctly."""
    source = b"@staticmethod\n@some_decorator\ndef compute(x: float) -> float:\n    return x * 2\n"
    fp = tmp_path / "multi_decorated.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    assert len(result.functions) == 1
    func = result.functions[0]
    assert func.name == "compute"


# ---------------------------------------------------------------------------
# AC7: Async function extracted identically to synchronous function
# ---------------------------------------------------------------------------


def test_async_function_extracted(parser: PythonParser, tmp_path: Path) -> None:
    """Given an async function, when parsed, then it is extracted identically to
    a synchronous function (same fields, same position)."""
    source = b"async def fetch(url: str) -> bytes:\n    pass\n"
    fp = tmp_path / "async_func.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    assert len(result.functions) == 1
    func = result.functions[0]
    assert func.name == "fetch"
    assert func.params[0].name == "url"
    assert func.params[0].type_annotation == "str"
    assert func.return_type == "bytes"
    assert func.start_line == 1


def test_async_and_sync_function_same_structure(
    parser: PythonParser, tmp_path: Path
) -> None:
    """Async and sync versions of the same function produce identical ParseResult
    shapes (only is_async differs)."""
    sync_source = b"def run(x: int) -> int:\n    return x\n"
    async_source = b"async def run(x: int) -> int:\n    return x\n"

    fp = tmp_path / "run.py"

    fp.write_bytes(sync_source)
    sync_result = parser.parse(sync_source, fp)

    fp.write_bytes(async_source)
    async_result = parser.parse(async_source, fp)

    assert len(sync_result.functions) == len(async_result.functions) == 1
    sf = sync_result.functions[0]
    af = async_result.functions[0]
    assert sf.name == af.name == "run"
    assert sf.params[0].name == af.params[0].name
    assert sf.params[0].type_annotation == af.params[0].type_annotation
    assert sf.return_type == af.return_type
    assert sf.start_line == af.start_line


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


def test_python_parser_implements_language_parser_protocol(
    parser: PythonParser,
) -> None:
    """PythonParser satisfies the LanguageParser Protocol (runtime_checkable)."""
    from apriori.structural.protocol import LanguageParser

    assert isinstance(parser, LanguageParser)


def test_parse_returns_parse_result(parser: PythonParser, tmp_path: Path) -> None:
    """parse() returns a ParseResult instance for any Python source."""
    source = b"x = 1\n"
    fp = tmp_path / "simple.py"
    fp.write_bytes(source)

    result = parser.parse(source, fp)

    assert isinstance(result, ParseResult)
    assert result.language == "python"
    assert result.file_path == fp
