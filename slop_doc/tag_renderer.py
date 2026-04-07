"""Tag renderer — resolves {{data}} tags and %presentation()% functions.

Two kinds of tags:

1. **Data tags** — ``{{classes}}``, ``{{functions}}``, ``{{constants}}``
   Always expand to a plain list of names (as a comma-separated linked list
   when used in Markdown body).

2. **Presentation functions** — ``%classes_table({{classes}})%``,
   ``%methods_details(ClassName)%``, etc.
   Render structured HTML (tables, detail blocks) from source data.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slop_doc.parser import SourceData, ClassData, FunctionData

from slop_doc.markdown_renderer import markdown_to_html


class TagRendererError(Exception):
    """Raised when tag rendering fails."""
    pass


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# {{classes}}, {{functions}}, {{constants}}
DATA_TAG_PATTERN = re.compile(r'\{\{(\w+)\}\}')

# %func_name(args)% — presentation functions
# Captures: func_name and the raw arguments string
PRES_FUNC_PATTERN = re.compile(r'%(\w+)\(([^)]*)\)%')


# ---------------------------------------------------------------------------
# Data-tag expansion  (always returns a list of names)
# ---------------------------------------------------------------------------

def expand_data_tag(tag_name: str, source_data: SourceData | None) -> list[str]:
    """Expand a data tag to a list of names.

    Plain tags (``classes``, ``functions``, ``constants``) return items from
    **direct** files in the source folder only (no subfolders).

    ``_rec`` variants (``classes_rec``, ``functions_rec``, ``constants_rec``)
    return items from the source folder **and all subfolders**.

    Args:
        tag_name: Tag name, e.g. 'classes', 'classes_rec'.
        source_data: Parsed source data.

    Returns:
        List of class/function/constant names.

    Raises:
        TagRendererError: If the tag is unknown or source_data is None.
    """
    if source_data is None:
        raise TagRendererError(
            f"Tag '{{{{{tag_name}}}}}' requires a source folder but none is set. "
            f"Set 'default_source_folder' in the page or a parent root.md front-matter."
        )

    # Mapping: tag_name -> (flat_attr, rec_attr)
    TAG_MAP = {
        'classes':     ('classes_flat', 'classes'),
        'functions':   ('functions_flat', 'functions'),
        'constants':   ('constants_flat', 'constants'),
        'enums':       ('enums_flat', 'enums'),
        'dataclasses': ('dataclasses_flat', 'dataclasses'),
        'interfaces':  ('interfaces_flat', 'interfaces'),
        'protocols':   ('protocols_flat', 'protocols'),
        'exceptions':    ('exceptions_flat', 'exceptions'),
        'plain_classes': ('plain_classes_flat', 'plain_classes'),
    }

    # Check for _rec suffix
    is_rec = tag_name.endswith('_rec')
    base_name = tag_name[:-4] if is_rec else tag_name

    if base_name not in TAG_MAP:
        raise TagRendererError(f"Unknown data tag: '{{{{{tag_name}}}}}'")

    flat_attr, rec_attr = TAG_MAP[base_name]
    items = getattr(source_data, rec_attr if is_rec else flat_attr)
    return [item.name for item in items]


def expand_data_tags_in_list(items: list, source_data: SourceData | None) -> list[str]:
    """Expand a list that may contain {{tag}} strings mixed with plain names.

    For example: ["{{classes}}", "ManualClass"] → ["ClassA", "ClassB", "ManualClass"]

    Args:
        items: List of strings, some may be {{tag}} patterns.
        source_data: Parsed source data.

    Returns:
        Flat list of names with all tags expanded.
    """
    result: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        m = DATA_TAG_PATTERN.fullmatch(item.strip())
        if m:
            result.extend(expand_data_tag(m.group(1), source_data))
        else:
            result.append(item.strip())
    return result


# ---------------------------------------------------------------------------
# Render data tags in Markdown body (inline — as linked name lists)
# ---------------------------------------------------------------------------

def render_data_tags_inline(body: str, source_data: SourceData | None, folder_slug: str = "") -> str:
    """Replace bare {{tag}} in Markdown body with a list of names.

    {{classes}} → cross-linked list: ``[[folder/ClassA]], [[folder/ClassB]]``
    {{functions}}, {{constants}} → plain comma-separated names (no links,
    since they don't have dedicated pages by default).
    """
    # Tags whose names should be cross-linked (all class-like types)
    LINKABLE_TAGS = {
        'classes', 'classes_rec',
        'enums', 'enums_rec',
        'dataclasses', 'dataclasses_rec',
        'interfaces', 'interfaces_rec',
        'protocols', 'protocols_rec',
        'exceptions', 'exceptions_rec',
        'plain_classes', 'plain_classes_rec',
    }

    def _replace(match):
        tag = match.group(1)
        names = expand_data_tag(tag, source_data)

        if not names:
            return "*None found.*"

        if folder_slug and tag in LINKABLE_TAGS:
            items = [f"[[{folder_slug}/{n}]]" for n in names]
        else:
            items = [f"`{n}`" for n in names]
        return ", ".join(items)

    return DATA_TAG_PATTERN.sub(_replace, body)


# ---------------------------------------------------------------------------
# Presentation functions  (%func(args)%)
# ---------------------------------------------------------------------------

def render_presentation_functions(
    body: str,
    source_data: SourceData | None,
    folder_slug: str = "",
    current_output_path: str = "",
) -> str:
    """Replace all %func(args)% in *body* with rendered HTML.

    Supported functions:
        %classes_table({{classes}})%   or  %classes_table(A, B)%
        %functions_table({{functions}})%
        %constants_table({{constants}})%
        %class_info(ClassName)%
        %properties(ClassName)%
        %methods_table(ClassName)%          — public methods summary table
        %methods_table(ClassName, private)% — private methods summary table
        %methods_details(ClassName)%        — full detail blocks
        %class_description(ClassName)%      — short + full description
        %base_classes(ClassName)%
        %decorators(ClassName)%
        %source_link(ClassName)%
    """
    def _replace(match):
        func_name = match.group(1)
        raw_args = match.group(2).strip()

        # %pdf(path/to/file.pdf)% — handled before dispatch (no source_data needed)
        if func_name == 'pdf':
            basename = raw_args.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
            return f'<div class="pdf-viewer" data-pdf-url="{basename}" data-pdf-src="{raw_args}"></div>'

        try:
            return _dispatch_presentation(func_name, raw_args, source_data, folder_slug, current_output_path)
        except TagRendererError as e:
            raise TagRendererError(f"Error in %{func_name}({raw_args})%: {e}")

    return PRES_FUNC_PATTERN.sub(_replace, body)


def _dispatch_presentation(
    func_name: str,
    raw_args: str,
    source_data: SourceData | None,
    folder_slug: str,
    current_output_path: str,
) -> str:
    """Dispatch a presentation function call to the correct renderer."""
    if source_data is None:
        raise TagRendererError(f"Presentation function '{func_name}' requires a source folder")

    # Parse arguments: expand any {{tag}} inside args, split by comma
    args = _parse_pres_args(raw_args, source_data)

    if func_name == 'classes_table':
        names = _resolve_name_list(args, 'classes', source_data)
        return _render_classes_table(source_data, names, folder_slug)

    if func_name == 'functions_table':
        names = _resolve_name_list(args, 'functions', source_data)
        return _render_functions_table(source_data, names)

    if func_name == 'constants_table':
        names = _resolve_name_list(args, 'constants', source_data)
        return _render_constants_table(source_data, names)

    if func_name == 'class_info':
        cls = _require_class(args, source_data)
        return _render_class_info(cls, source_data, folder_slug)

    if func_name == 'properties':
        cls = _require_class(args, source_data)
        return _render_properties(cls)

    if func_name == 'methods_table':
        cls_name, method_type = _parse_class_and_option(args, default_option='public')
        cls = _find_class(cls_name, source_data)
        return _render_methods_summary(cls, method_type, folder_slug, current_output_path, source_data)

    if func_name == 'methods_details':
        cls = _require_class(args, source_data)
        return _render_methods_details(cls, source_data, folder_slug)

    if func_name == 'class_description':
        cls = _require_class(args, source_data)
        short = cls.short_description or ""
        full = cls.full_description or ""
        if full and full != short:
            return f"{short}\n\n{full}"
        return short

    if func_name == 'base_classes':
        cls = _require_class(args, source_data)
        return ", ".join(cls.base_classes) if cls.base_classes else "(none)"

    if func_name == 'decorators':
        cls = _require_class(args, source_data)
        return ", ".join(cls.decorators) if cls.decorators else ""

    if func_name == 'source_link':
        cls = _require_class(args, source_data)
        return f"{cls.source_file}:{cls.source_line}"

    raise TagRendererError(f"Unknown presentation function: '{func_name}'")


# ---------------------------------------------------------------------------
# Argument helpers
# ---------------------------------------------------------------------------

def _parse_pres_args(raw: str, source_data: SourceData | None) -> list[str]:
    """Split raw args string, expanding any {{tag}} inline."""
    if not raw:
        return []

    # First expand {{tag}} into comma-separated names
    expanded = DATA_TAG_PATTERN.sub(
        lambda m: ", ".join(expand_data_tag(m.group(1), source_data)),
        raw
    )
    return [a.strip() for a in expanded.split(',') if a.strip()]


def _resolve_name_list(args: list[str], tag_type: str, source_data: SourceData) -> list[str]:
    """Return a list of names; if args is empty use all from source_data."""
    if args:
        return args
    return expand_data_tag(tag_type, source_data)


def _require_class(args: list[str], source_data: SourceData) -> ClassData:
    """First arg must be a class name."""
    if not args:
        raise TagRendererError("Class name required")
    return _find_class(args[0], source_data)


def _find_class(name: str, source_data: SourceData) -> ClassData:
    for cls in source_data.classes:
        if cls.name == name:
            return cls
    raise TagRendererError(f"Class '{name}' not found in source data")


def _parse_class_and_option(args: list[str], default_option: str) -> tuple[str, str]:
    """Parse (ClassName) or (ClassName, option)."""
    if not args:
        raise TagRendererError("Class name required")
    cls_name = args[0]
    option = args[1] if len(args) > 1 else default_option
    return cls_name, option


# ---------------------------------------------------------------------------
# HTML rendering helpers  (ported from template_engine.py)
# ---------------------------------------------------------------------------

def _render_classes_table(source_data: SourceData, names: list[str], folder_slug: str) -> str:
    if not names:
        return ""

    cls_map = {c.name: c for c in source_data.classes}
    rows = []
    for name in names:
        cls = cls_map.get(name)
        desc = cls.short_description if cls else "No description"
        link = f"[[{folder_slug}/{name}]]" if folder_slug else name
        rows.append(f"<tr><td>{link}</td><td>{desc or 'No description'}</td></tr>")

    return (
        "<table class='classes-table'>\n"
        "<thead><tr><th>Class</th><th>Description</th></tr></thead>\n"
        f"<tbody>\n{''.join(rows)}\n</tbody>\n</table>"
    )


def _render_functions_table(source_data: SourceData, names: list[str]) -> str:
    if not names:
        return ""

    func_map = {f.name: f for f in source_data.functions}
    rows = []
    for name in names:
        func = func_map.get(name)
        if func:
            sig = _render_function_signature(func)
            desc = func.short_description or "No description"
        else:
            sig = name
            desc = "No description"
        rows.append(f"<tr><td>{sig}</td><td>{desc}</td></tr>")

    return (
        "<table class='functions-table'>\n"
        "<thead><tr><th>Function</th><th>Description</th></tr></thead>\n"
        f"<tbody>\n{''.join(rows)}\n</tbody>\n</table>"
    )


def _render_constants_table(source_data: SourceData, names: list[str]) -> str:
    if not names:
        return ""

    const_map = {c.name: c for c in source_data.constants}
    rows = []
    for name in names:
        const = const_map.get(name)
        if const:
            rows.append(f"<tr><td>{const.name}</td><td>{const.value}</td><td>{const.type}</td></tr>")
        else:
            rows.append(f"<tr><td>{name}</td><td>—</td><td>—</td></tr>")

    return (
        "<table class='constants-table'>\n"
        "<thead><tr><th>Name</th><th>Value</th><th>Type</th></tr></thead>\n"
        f"<tbody>\n{''.join(rows)}\n</tbody>\n</table>"
    )


def _render_class_info(class_data: ClassData, source_data: SourceData | None = None, folder_slug: str = "") -> str:
    rel_file = os.path.relpath(class_data.source_file).replace('\\', '/')
    module_name = os.path.splitext(os.path.basename(class_data.source_file))[0]

    # Render base classes with cross-links for project classes
    if class_data.base_classes:
        existing_names = {cls.name for cls in source_data.classes} if source_data else set()
        parts = []
        for bc in class_data.base_classes:
            if bc in existing_names and folder_slug:
                parts.append(f"[[{folder_slug}/{bc}]]")
            else:
                parts.append(bc)
        inherits_str = ', '.join(parts)
    else:
        inherits_str = '(none)'

    return (
        "<table class='class-info'>\n"
        f"<tr><td>Module:</td><td>{module_name}</td></tr>\n"
        f"<tr><td>File:</td><td>{rel_file}:{class_data.source_line}</td></tr>\n"
        f"<tr><td>Inherits:</td><td>{inherits_str}</td></tr>\n"
        "</table>"
    )


def _render_properties(class_data: ClassData) -> str:
    if not class_data.properties:
        return ""

    rows = []
    for prop in class_data.properties:
        rows.append(f"<tr><td>{prop.name}</td><td>{prop.type or 'Unknown'}</td><td>{prop.description}</td></tr>")

    return (
        "<table class='properties-table'>\n"
        "<thead><tr><th>Name</th><th>Type</th><th>Description</th></tr></thead>\n"
        f"<tbody>\n{''.join(rows)}\n</tbody>\n</table>"
    )


def _render_methods_summary(
    class_data: ClassData,
    method_type: str,
    folder_slug: str,
    current_output_path: str,
    source_data: SourceData,
) -> str:
    methods = _filter_methods(class_data, method_type)
    if not methods:
        return ""

    rows = []
    for method in methods:
        sig = _render_function_signature(method, source_data, folder_slug)
        desc_html = markdown_to_html(method.short_description or "No description")
        link = f"[[{folder_slug}/{class_data.name}.{method.name}]]" if folder_slug else method.name
        rows.append(f"<tr><td>{link}{sig[len(method.name):]}</td><td>{desc_html}</td></tr>")

    return (
        "<table class='methods-table'>\n"
        "<thead><tr><th>Signature</th><th>Description</th></tr></thead>\n"
        f"<tbody>\n{''.join(rows)}\n</tbody>\n</table>"
    )


def _render_methods_details(class_data: ClassData, source_data: SourceData, folder_slug: str) -> str:
    methods = _filter_methods(class_data, 'public') + _filter_methods(class_data, 'private')
    if not methods:
        return ""

    parts = []
    for method in methods:
        # Build params string
        params_parts = []
        for arg in method.args:
            if arg.name == 'self':
                continue
            if arg.type:
                type_str = link_type_if_class(arg.type, source_data, folder_slug)
                params_parts.append(f"{arg.name}: {type_str}")
            else:
                params_parts.append(arg.name)
        params_str = ", ".join(params_parts)

        html = f'<div class="method-detail">\n'
        html += f'<h3 id="{method.name}"><span class="method-name">{method.name}</span>'
        html += f'<span class="method-params">({params_str})</span></h3>\n'
        html += '<div class="method-body">\n'

        if method.short_description:
            html += f'{markdown_to_html(method.short_description)}\n'
        if method.full_description and method.full_description != method.short_description:
            full_desc_stripped = '\n'.join(line.lstrip() for line in method.full_description.split('\n'))
            html += f'{markdown_to_html(full_desc_stripped)}\n'

        if method.parameters:
            html += '<h4>Parameters</h4>\n<dl class="params-list">\n'
            for param in method.parameters:
                opt = " <em>(optional)</em>" if param.is_optional else ""
                html += f'<dd><code>{param.name}</code> — {param.description}{opt}</dd>\n'
            html += '</dl>\n'

        if method.returns:
            ret_type = method.returns.type or method.return_type or ""
            ret_desc = method.returns.description or ""
            if ret_type:
                type_str = link_type_if_class(ret_type, source_data, folder_slug)
                html += f'<h4>Returns</h4>\n<div class="returns-block"><code>{type_str}</code> — {ret_desc}</div>\n'
            else:
                html += f'<h4>Returns</h4>\n<div class="returns-block">{ret_desc}</div>\n'
        elif method.return_type and method.return_type not in ('None', 'none'):
            type_str = link_type_if_class(method.return_type, source_data, folder_slug)
            html += f'<h4>Returns</h4>\n<div class="returns-block"><code>{type_str}</code></div>\n'

        if method.raises:
            html += '<h4>Raises</h4>\n<dl class="raises-list">\n'
            for raise_doc in method.raises:
                type_str = link_type_if_class(raise_doc.type, source_data, folder_slug)
                html += f'<dd><code>{type_str}</code> — {raise_doc.description}</dd>\n'
            html += '</dl>\n'

        html += '</div>\n</div>\n'
        parts.append(html)

    return '\n'.join(parts)


def render_function_detail(func: FunctionData, source_data: SourceData | None, folder_slug: str) -> str:
    """Render a single function's full detail block (like a method detail but for standalone functions)."""
    params_parts = []
    for arg in func.args:
        if arg.type:
            type_str = link_type_if_class(arg.type, source_data, folder_slug)
            params_parts.append(f"{arg.name}: {type_str}")
        else:
            params_parts.append(arg.name)
    params_str = ", ".join(params_parts)

    html = f'<div class="method-detail">\n'
    html += f'<h3 id="{func.name}"><span class="method-name">{func.name}</span>'
    html += f'<span class="method-params">({params_str})</span>'
    if func.return_type:
        ret_type = link_type_if_class(func.return_type, source_data, folder_slug)
        html += f' <span class="method-return">-&gt; {ret_type}</span>'
    html += '</h3>\n'
    html += '<div class="method-body">\n'

    if func.short_description:
        html += f'{markdown_to_html(func.short_description)}\n'
    if func.full_description and func.full_description != func.short_description:
        full_desc_stripped = '\n'.join(line.lstrip() for line in func.full_description.split('\n'))
        html += f'{markdown_to_html(full_desc_stripped)}\n'

    if func.parameters:
        html += '<h4>Parameters</h4>\n<dl class="params-list">\n'
        for param in func.parameters:
            opt = " <em>(optional)</em>" if param.is_optional else ""
            html += f'<dd><code>{param.name}</code> — {param.description}{opt}</dd>\n'
        html += '</dl>\n'

    if func.returns:
        ret_type = func.returns.type or func.return_type or ""
        ret_desc = func.returns.description or ""
        if ret_type:
            type_str = link_type_if_class(ret_type, source_data, folder_slug)
            html += f'<h4>Returns</h4>\n<div class="returns-block"><code>{type_str}</code> — {ret_desc}</div>\n'
        else:
            html += f'<h4>Returns</h4>\n<div class="returns-block">{ret_desc}</div>\n'
    elif func.return_type and func.return_type not in ('None', 'none'):
        type_str = link_type_if_class(func.return_type, source_data, folder_slug)
        html += f'<h4>Returns</h4>\n<div class="returns-block"><code>{type_str}</code></div>\n'

    if func.raises:
        html += '<h4>Raises</h4>\n<dl class="raises-list">\n'
        for raise_doc in func.raises:
            type_str = link_type_if_class(raise_doc.type, source_data, folder_slug)
            html += f'<dd><code>{type_str}</code> — {raise_doc.description}</dd>\n'
        html += '</dl>\n'

    html += '</div>\n</div>\n'
    return html


# ---------------------------------------------------------------------------
# Method filtering
# ---------------------------------------------------------------------------

def _filter_methods(class_data: ClassData, method_type: str) -> list[FunctionData]:
    """Filter methods by type: 'public', 'private', 'static', 'classmethod', 'dunder', 'all'."""
    methods = []
    for method in class_data.methods:
        is_static = 'staticmethod' in method.decorators
        is_class = 'classmethod' in method.decorators
        is_private = method.name.startswith('_') and not method.name.startswith('__')
        is_dunder = method.name.startswith('__')

        if method_type == 'public' and (is_private or is_dunder or is_static or is_class):
            continue
        if method_type == 'private' and not (is_private and not is_dunder):
            continue
        if method_type == 'static' and not is_static:
            continue
        if method_type == 'classmethod' and not is_class:
            continue
        if method_type == 'dunder' and not is_dunder:
            continue
        if method_type == 'all' and (is_private and not is_dunder):
            continue

        methods.append(method)
    return methods


# ---------------------------------------------------------------------------
# Signature rendering + type linking  (ported from template_engine.py)
# ---------------------------------------------------------------------------

def _render_function_signature(func: FunctionData, source_data: SourceData | None = None, folder_slug: str = "") -> str:
    args = []
    for arg in func.args:
        if arg.name == 'self':
            continue
        arg_str = arg.name
        if arg.type:
            type_str = link_type_if_class(arg.type, source_data, folder_slug)
            arg_str = f"{arg_str}: {type_str}"
        if arg.default:
            arg_str = f"{arg_str}={arg.default}"
        args.append(arg_str)

    sig = f"{func.name}({', '.join(args)})"
    if func.return_type:
        type_str = link_type_if_class(func.return_type, source_data, folder_slug)
        sig = f"{sig} -> {type_str}"
    return sig


def link_type_if_class(type_str: str, source_data: SourceData | None, folder_slug: str) -> str:
    if not source_data or not folder_slug:
        return type_str

    existing = {cls.name for cls in source_data.classes}
    # Use regex substitution with word boundaries to avoid collisions
    # (e.g., list[ClassName] → list[ [[folder/ClassName]] ] instead of list[[[folder/ClassName]]])
    def _replace(m):
        name = m.group(0)
        if name in existing:
            return f" [[{folder_slug}/{name}]] "
        return name

    return re.sub(r'\b([A-Z][a-zA-Z0-9_]*)\b', _replace, type_str)
