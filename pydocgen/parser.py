"""Stage 1: Python Source Parser - extracts structured data from Python source files."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ArgData:
    """Represents a function argument."""
    name: str
    type: str | None
    default: str | None


@dataclass
class ParamDoc:
    """Represents a parameter from a docstring."""
    name: str
    type: str | None
    description: str
    is_optional: bool = False


@dataclass
class ReturnDoc:
    """Represents a return value from a docstring."""
    type: str | None
    description: str


@dataclass
class RaiseDoc:
    """Represents an exception from a docstring."""
    type: str
    description: str


@dataclass
class FunctionData:
    """Represents a parsed function."""
    name: str
    args: list[ArgData] = field(default_factory=list)
    return_type: str | None = None
    decorators: list[str] = field(default_factory=list)
    short_description: str = ""
    full_description: str = ""
    parameters: list[ParamDoc] = field(default_factory=list)
    returns: ReturnDoc | None = None
    raises: list[RaiseDoc] = field(default_factory=list)
    examples: str = ""
    source_file: str = ""
    source_line: int = 0


@dataclass
class PropertyData:
    """Represents a property."""
    name: str
    type: str | None
    description: str


@dataclass
class ClassData:
    """Represents a parsed class."""
    name: str
    base_classes: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    short_description: str = ""
    full_description: str = ""
    properties: list[PropertyData] = field(default_factory=list)
    methods: list[FunctionData] = field(default_factory=list)
    source_file: str = ""
    source_line: int = 0


@dataclass
class ConstantData:
    """Represents a module-level constant."""
    name: str
    value: str
    type: str


@dataclass
class SourceData:
    """Container for all parsed source data from a module."""
    classes: list[ClassData] = field(default_factory=list)
    functions: list[FunctionData] = field(default_factory=list)
    constants: list[ConstantData] = field(default_factory=list)


def parse_google_docstring(docstring: str) -> tuple[str, str, list[ParamDoc], ReturnDoc | None, list[RaiseDoc], str]:
    """Parse a Google-style docstring into structured components.

    Returns:
        (short_description, full_description, parameters, returns, raises, examples)
    """
    if not docstring:
        return "", "", [], None, [], ""

    lines = docstring.split('\n')
    short_desc = ""
    full_desc = ""
    parameters: list[ParamDoc] = []
    returns: ReturnDoc | None = None
    raises: list[RaiseDoc] = []
    examples = ""

    current_section = "short"
    section_content: list[str] = []
    current_param: ParamDoc | None = None

    for line in lines:
        stripped = line.strip()

        # Check for section headers
        if stripped.startswith("Args:") or stripped.startswith("Arguments:"):
            if short_desc == "" and full_desc == "" and section_content:
                full_desc = "\n".join(section_content).strip()
                section_content = []
            current_section = "args"
            continue
        elif stripped.startswith("Returns:"):
            if section_content and current_section == "args":
                _finish_current_param(section_content, parameters)
                section_content = []
            current_section = "returns"
            continue
        elif stripped.startswith("Raises:"):
            if section_content and current_section == "returns":
                # Process returns section before transitioning
                ret_text = " ".join(section_content)
                ret_type = None
                ret_desc = ret_text
                if "—" in ret_text:
                    parts = ret_text.split("—", 1)
                    ret_type = parts[0].strip()
                    ret_desc = parts[1].strip()
                elif "->" in ret_text:
                    parts = ret_text.split("->", 1)
                    ret_type = parts[0].strip()
                    ret_desc = parts[1].strip()
                returns = ReturnDoc(type=ret_type, description=ret_desc)
                section_content = []
            current_section = "raises"
            continue
        elif stripped.startswith("Examples:") or stripped.startswith("Example:"):
            if section_content and current_section == "returns":
                # Process returns section before transitioning
                ret_text = " ".join(section_content)
                ret_type = None
                ret_desc = ret_text
                if "—" in ret_text:
                    parts = ret_text.split("—", 1)
                    ret_type = parts[0].strip()
                    ret_desc = parts[1].strip()
                elif "->" in ret_text:
                    parts = ret_text.split("->", 1)
                    ret_type = parts[0].strip()
                    ret_desc = parts[1].strip()
                returns = ReturnDoc(type=ret_type, description=ret_desc)
                section_content = []
            current_section = "examples"
            continue
        elif stripped.startswith("=") and len(stripped) > 3 and current_section != "short":
            # Skip separator lines
            continue
        elif not stripped:
            # Empty line might separate sections
            if current_section == "args" and current_param:
                _finish_current_param(section_content, parameters)
                current_param = None
                section_content = []
            continue

        # Content lines
        if current_section == "short":
            if short_desc == "" and stripped:
                short_desc = stripped
                if len(lines) == 1:
                    full_desc = short_desc
            elif stripped:
                full_desc += ("\n" if full_desc else "") + stripped
        elif current_section == "args":
            # Parse arg lines like "    name: Type description" or "    name: description"
            content_line = line.lstrip()
            indent = len(line) - len(content_line)

            if content_line and not content_line.startswith(":") and indent > 0:
                # Could be a parameter line
                if ":" in content_line:
                    # Finish previous param if exists
                    if current_param:
                        _finish_current_param(section_content, parameters)

                    parts = content_line.split(":", 1)
                    arg_name = parts[0].strip()
                    rest = parts[1].strip() if len(parts) > 1 else ""

                    # Parse type from "Type, optional" or just "Type"
                    arg_type = None
                    desc = rest
                    is_optional = False

                    if "," in rest:
                        type_part, desc_part = rest.split(",", 1)
                        arg_type = type_part.strip()
                        desc = desc_part.strip()
                        is_optional = "optional" in desc_part.lower()
                    elif rest:
                        # No comma - the rest is description, not type
                        desc = rest
                        arg_type = None

                    current_param = ParamDoc(
                        name=arg_name,
                        type=arg_type if arg_type else None,
                        description=desc,
                        is_optional=is_optional
                    )
                    parameters.append(current_param)
                    section_content = []
                elif current_param:
                    # Continuation of previous param description
                    section_content.append(stripped)
            elif content_line.startswith(":") and current_param:
                # Docstring arg format like "    arg_name: Description"
                section_content.append(stripped)
        elif current_section == "returns":
            section_content.append(stripped)
        elif current_section == "raises":
            # Format: ExceptionType: description
            if ":" in stripped:
                exc_type, desc = stripped.split(":", 1)
                raises.append(RaiseDoc(type=exc_type.strip(), description=desc.strip()))
        elif current_section == "examples":
            examples += stripped + "\n"

    # Finish any remaining content
    if current_section == "args" and current_param:
        _finish_current_param(section_content, parameters)
    elif current_section == "returns" and section_content:
        ret_text = " ".join(section_content)
        # Try to parse return type
        ret_type = None
        ret_desc = ret_text
        if "—" in ret_text:
            parts = ret_text.split("—", 1)
            ret_type = parts[0].strip()
            ret_desc = parts[1].strip()
        elif "->" in ret_text:
            parts = ret_text.split("->", 1)
            ret_type = parts[0].strip()
            ret_desc = parts[1].strip()
        returns = ReturnDoc(type=ret_type, description=ret_desc)

    return short_desc, full_desc, parameters, returns, raises, examples.strip()


def _finish_current_param(section_content: list[str], parameters: list[ParamDoc]) -> None:
    """Helper to finish parsing a current parameter."""
    if section_content:
        param = parameters[-1] if parameters else None
        if param:
            param.description = (param.description + " " + " ".join(section_content)).strip()


def _get_class_decorators(node: ast.ClassDef) -> list[str]:
    """Extract class decorators."""
    return [d.attr if isinstance(d, ast.Attribute) else d.name for d in node.decorator_list]


def _get_function_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Extract function decorators."""
    decorators = []
    for d in node.decorator_list:
        if isinstance(d, ast.Name):
            decorators.append(d.id)
        elif isinstance(d, ast.Attribute):
            decorators.append(d.attr)
        elif isinstance(d, ast.Call):
            if isinstance(d.func, ast.Name):
                decorators.append(d.func.id)
            elif isinstance(d.func, ast.Attribute):
                decorators.append(d.func.attr)
    return decorators


def _parse_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ArgData]:
    """Parse function arguments from AST."""
    args_data = []
    for arg in node.args.args:
        arg_type = None
        if arg.annotation:
            arg_type = _get_annotation_name(arg.annotation)

        default = None
        if node.args.defaults:
            # Map defaults to args from the right
            arg_index = len(node.args.args) - 1
            for i, default_expr in enumerate(reversed(node.args.defaults)):
                if len(node.args.args) - 1 - i == arg_index:
                    default = _get_default_value(default_expr)
                    break
            arg_index -= 1

        args_data.append(ArgData(name=arg.arg, type=arg_type, default=default))
    return args_data


def _get_annotation_name(annotation: ast.expr) -> str:
    """Get the name of a type annotation."""
    if isinstance(annotation, ast.Name):
        return annotation.id
    elif isinstance(annotation, ast.Attribute):
        return f"{_get_annotation_name(annotation.value)}.{annotation.attr}"
    elif isinstance(annotation, ast.Subscript):
        return f"{_get_annotation_name(annotation.value)}[{_get_annotation_name(annotation.slice)}]"
    elif isinstance(annotation, ast.Constant):
        return str(annotation.value)
    return "Unknown"


def _get_default_value(expr: ast.expr) -> str:
    """Get string representation of a default value expression."""
    if isinstance(expr, ast.Constant):
        return repr(expr.value)
    elif isinstance(expr, ast.Name):
        return expr.id
    elif isinstance(expr, ast.Attribute):
        return f"{_get_default_value(expr.value)}.{expr.attr}"
    elif isinstance(expr, ast.BinOp):
        return f"{_get_default_value(expr.left)} {_get_binop_symbol(expr.op)} {_get_default_value(expr.right)}"
    elif isinstance(expr, ast.UnaryOp):
        return f"{_get_unaryop_symbol(expr.op)}{_get_default_value(expr.operand)}"
    return "..."


def _get_binop_symbol(op: ast.operator) -> str:
    ops = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.FloorDiv: "//", ast.Mod: "%"}
    return ops.get(type(op), "?")


def _get_unaryop_symbol(op: ast.unaryop) -> str:
    ops = {ast.UAdd: "+", ast.USub: "-", ast.Not: "not "}
    return ops.get(type(op), "")


def _parse_function(node: ast.FunctionDef | ast.AsyncFunctionDef, source_file: str) -> FunctionData:
    """Parse a function definition into FunctionData."""
    short_desc, full_desc, params, returns, raises, examples = parse_google_docstring(ast.get_docstring(node))

    # If no docstring parsed, try type hints for return type
    return_type = None
    if node.returns:
        return_type = _get_annotation_name(node.returns)

    return FunctionData(
        name=node.name,
        args=_parse_args(node),
        return_type=return_type,
        decorators=_get_function_decorators(node),
        short_description=short_desc,
        full_description=full_desc,
        parameters=params,
        returns=returns,
        raises=raises,
        examples=examples,
        source_file=source_file,
        source_line=node.lineno
    )


def _parse_class(node: ast.ClassDef, source_file: str) -> ClassData:
    """Parse a class definition into ClassData."""
    short_desc, full_desc, _, _, _, _ = parse_google_docstring(ast.get_docstring(node))

    # Get base classes
    base_classes = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            base_classes.append(base.id)
        elif isinstance(base, ast.Attribute):
            base_classes.append(_get_annotation_name(base))

    # Separate methods by type
    methods: list[FunctionData] = []
    properties: list[PropertyData] = []

    for item in node.body:
        if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
            func_data = _parse_function(item, source_file)
            # Check if it's a property
            if "property" in func_data.decorators:
                # Get return type from type hint
                prop_type = None
                if item.returns:
                    prop_type = _get_annotation_name(item.returns)
                properties.append(PropertyData(
                    name=item.name,
                    type=prop_type,
                    description=func_data.short_description
                ))
            else:
                methods.append(func_data)

    return ClassData(
        name=node.name,
        base_classes=base_classes,
        decorators=_get_class_decorators(node),
        short_description=short_desc,
        full_description=full_desc,
        properties=properties,
        methods=methods,
        source_file=source_file,
        source_line=node.lineno
    )


def parse_file(filepath: str) -> SourceData:
    """Parse a Python file and return SourceData.

    Args:
        filepath: Path to the Python file to parse.

    Returns:
        SourceData containing all classes, functions, and constants.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source, filename=filepath)

    classes: list[ClassData] = []
    functions: list[FunctionData] = []
    constants: list[ConstantData] = []

    # Get module-level constants (ALL_CAPS variables)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    value_str = _get_default_value(node.value)
                    const_type = "Unknown"
                    if node.value and hasattr(node.value, 'id'):
                        const_type = type(node.value).__name__
                    elif isinstance(node.value, ast.Constant):
                        const_type = type(node.value.value).__name__
                    constants.append(ConstantData(
                        name=target.id,
                        value=value_str,
                        type=const_type
                    ))

    # Get classes and top-level functions
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Skip private classes
            if node.name.startswith("_") and not node.name.startswith("__"):
                continue
            if node.name.startswith("__") and node.name.endswith("__"):
                # Dunder classes - include them
                pass
            elif node.name.startswith("_"):
                continue
            classes.append(_parse_class(node, filepath))

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip private and dunder functions at module level
            if node.name.startswith("_") and not node.name.startswith("__"):
                continue
            if node.name.startswith("__"):
                continue
            # Only top-level functions (not inside classes)
            if isinstance(node.parent if hasattr(node, 'parent') else None, ast.Module):
                pass
            # Simpler check: functions defined directly in Module
            functions.append(_parse_function(node, filepath))

    # Filter to only top-level functions (re-parse correctly)
    top_level_functions = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_") and not (node.name.startswith("__") and node.name.endswith("__")):
                top_level_functions.append(_parse_function(node, filepath))

    return SourceData(
        classes=classes,
        functions=top_level_functions,
        constants=constants
    )


def parse_folder(folder_path: str) -> SourceData:
    """Parse all Python files in a folder and merge SourceData.

    Args:
        folder_path: Path to the folder containing Python files.

    Returns:
        Merged SourceData from all Python files in the folder.
    """
    all_classes: list[ClassData] = []
    all_functions: list[FunctionData] = []
    all_constants: list[ConstantData] = []

    for root, _, files in os.walk(folder_path):
        for filename in sorted(files):
            if filename.endswith(".py"):
                filepath = os.path.join(root, filename)
                try:
                    data = parse_file(filepath)
                    all_classes.extend(data.classes)
                    all_functions.extend(data.functions)
                    all_constants.extend(data.constants)
                except Exception:
                    # Skip files that can't be parsed
                    pass

    return SourceData(
        classes=all_classes,
        functions=all_functions,
        constants=all_constants
    )
