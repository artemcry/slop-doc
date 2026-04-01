"""Stage 3: Template Engine - processes .dtmpl template files."""

from __future__ import annotations

import re
from typing import Any

from pydocgen.parser import SourceData
from pydocgen.markdown_renderer import markdown_to_html


class TemplateEngineError(Exception):
    """Raised when template processing fails."""
    pass


# Parameter pattern: param@NAME or param@NAME=default
PARAM_PATTERN = re.compile(r'^param@(\w+)(?:=(.*))?$')

# %%PARAM%% substitution pattern
SUBST_PATTERN = re.compile(r'%%(\w+)%%')

# For loop pattern: :: for X in {{collection}}.exclude("..."): ... :: endfor
# Note: The endfor must be on its own line (possibly indented)
FOR_LOOP_PATTERN = re.compile(r'::\s*for\s+(\w+)\s+in\s+([^\n]+?)\s*::\s*endfor', re.DOTALL)

# Data tag patterns
DATA_TAG_PATTERN = re.compile(r'\{\{(\w+)(?:#(\w+))?(?::\s*([^}]+))?\}\}')


def parse_params_block(template_content: str) -> tuple[dict[str, str | None], dict[str, str], str]:
    """Parse the parameter block at the top of a template.

    Args:
        template_content: The raw template content.

    Returns:
        Tuple of (required_params, optional_params, body)
        - required_params: dict of param_name -> None (no default)
        - optional_params: dict of param_name -> default_value
        - body: The template body after the param block
    """
    lines = template_content.split('\n')
    required_params: dict[str, None] = {}
    optional_params: dict[str, str] = {}

    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            body_start = i + 1
            break

        match = PARAM_PATTERN.match(stripped)
        if match:
            name = match.group(1)
            default = match.group(2)
            if default is None:
                required_params[name] = None
            else:
                optional_params[name] = default
            body_start = i + 1
        else:
            # First non-param@ line ends the param block
            body_start = i
            break

    body = '\n'.join(lines[body_start:])
    return required_params, optional_params, body


def validate_params(required: dict[str, None], all_params: dict[str, str]) -> None:
    """Validate that all required params are provided.

    Args:
        required: Dict of required param names to None.
        all_params: Dict of all param names (required + optional with values).

    Raises:
        TemplateEngineError: If a required param is missing.
    """
    for name in required:
        if name not in all_params:
            raise TemplateEngineError(f"Required param '{name}' not provided")


def substitute_params(body: str, params: dict[str, str]) -> str:
    """Substitute %%PARAM%% patterns in body.

    Args:
        body: Template body with %%PARAM%% patterns.
        params: Dict of param values.

    Returns:
        Body with all %%PARAM%% substituted.

    Raises:
        TemplateEngineError: If a %%PARAM%% is used but not declared.
    """
    # Find all %%PARAM%% in body
    for match in SUBST_PATTERN.finditer(body):
        param_name = match.group(1)
        if param_name not in params:
            raise TemplateEngineError(f"Unknown param %%{param_name}%%")

    # Replace all %%PARAM%% with their values
    result = body
    for name, value in params.items():
        result = result.replace(f'%%{name}%%', value)

    return result


def expand_for_loops(body: str, source_data: SourceData | None) -> str:
    """Expand :: for ... :: endfor loops.

    Args:
        body: Template body with for loops.
        source_data: SourceData object for data tag evaluation.

    Returns:
        Body with for loops expanded.

    Raises:
        TemplateEngineError: If a for loop references unknown collection or class.
    """
    if source_data is None:
        # If no source data, for loops that use data tags should error
        if ':: for ' in body:
            raise TemplateEngineError("Data tag {{classes}} requires source, but node has no source")
        return body

    # Pattern: :: for VAR in EXPR:\nBODY\n:: endfor
    pattern = r'::\s*for\s+(\w+)\s+in\s+([^\n]*)\n(.*?)\n\s*::\s*endfor'

    while True:
        match = re.search(pattern, body, re.DOTALL)
        if not match:
            break

        var_name = match.group(1)  # e.g., "X"
        collection_expr = match.group(2).strip()  # e.g., "{{classes}}.exclude('B')"
        # Remove trailing colon from the expression (from "EXPR:\n")
        collection_expr = collection_expr.rstrip(':').strip()
        loop_inner = match.group(3)  # The body content

        # Parse the collection expression
        collection_result = evaluate_collection_expr(collection_expr, source_data, var_name)

        # Expand for each item
        expanded_lines = []
        for item in collection_result:
            # Replace #var_name with item name in the body
            # e.g., {{class_name#X}} becomes {{class_name#Pipeline}}
            expanded = loop_inner.replace(f'#{var_name}', f'#{item}')
            expanded_lines.append(expanded)

        # Replace the entire for loop with expanded content
        body = body[:match.start()] + '\n'.join(expanded_lines) + body[match.end():]

    return body


def evaluate_collection_expr(expr: str, source_data: SourceData | None, var_name: str) -> list[str]:
    """Evaluate a collection expression like '{{classes}}' or '{{classes}}.exclude("B")'.

    Args:
        expr: The collection expression string.
        source_data: SourceData for evaluating data tags.
        var_name: The variable name used in the for loop.

    Returns:
        List of class/function names.

    Raises:
        TemplateEngineError: If collection is unknown or class doesn't exist.
    """
    expr = expr.strip()

    # Check for .exclude() modifier
    exclude_match = re.search(r'\.exclude\(\s*(["\']?[\w]+["\']?(?:\s*,\s*["\']?[\w]+["\']?)*)\s*\)', expr)
    exclude_names = []
    if exclude_match:
        exclude_str = exclude_match.group(1)
        # Parse comma-separated names
        for name in exclude_str.split(','):
            name = name.strip().strip('"\'')
            exclude_names.append(name)
        expr = expr[:exclude_match.start()] + expr[exclude_match.end():]

    # Extract the data tag
    data_match = re.match(r'\{\{(\w+)(?:#(\w+))?\}\}', expr.strip())
    if not data_match:
        raise TemplateEngineError(f"Unknown collection in for loop: {expr}")

    tag_name = data_match.group(1)  # e.g., "classes"
    # target = data_match.group(2)  # would be the class name for class-specific tags

    if source_data is None:
        raise TemplateEngineError(f"Data tag {{{{{tag_name}}}}} requires source, but node has no source")

    # Get the collection
    if tag_name == 'classes':
        collection = [c.name for c in source_data.classes]
    elif tag_name == 'functions':
        collection = [f.name for f in source_data.functions]
    elif tag_name == 'constants':
        collection = [c.name for c in source_data.constants]
    elif tag_name == 'classes_all':
        collection = [c.name for c in source_data.classes]
    elif tag_name == 'functions_all':
        collection = [f.name for f in source_data.functions]
    else:
        raise TemplateEngineError(f"Unknown data tag: {{{{{tag_name}}}}}")

    # Apply excludes
    collection = [c for c in collection if c not in exclude_names]

    return collection


def render_data_tag(tag: str, target: str | None, modifier: str | None, source_data: SourceData | None, folder_slug: str = "", current_output_path: str = "") -> str:
    """Render a {{data_tag}} or {{data_tag#target}} tag.

    Args:
        tag: The tag name (e.g., "classes", "public_methods").
        target: The target name if present (e.g., "Pipeline").
        modifier: Optional modifier (e.g., "run,stop" for methods_filtered).
        source_data: SourceData for looking up class/function info.
        folder_slug: Folder slug for generating class links.
        current_output_path: Output path of the current page being rendered.

    Returns:
        Rendered HTML string.

    Raises:
        TemplateEngineError: If tag or target is unknown.
    """
    if source_data is None:
        raise TemplateEngineError(f"Tag {{{{{tag}}}}} requires source, but node has no source")

    # Module-level tags (no target)
    if tag == 'classes':
        if target:
            raise TemplateEngineError(f"Tag {{{{{tag}}}}} does not take a target")
        return _render_classes_table(source_data, folder_slug)

    if tag == 'functions':
        if target:
            raise TemplateEngineError(f"Tag {{{{{tag}}}}} does not take a target")
        return _render_functions_table(source_data)

    if tag == 'constants':
        if target:
            raise TemplateEngineError(f"Tag {{{{{tag}}}}} does not take a target")
        return _render_constants_table(source_data)

    # Class-level tags (require target)
    if target is None:
        raise TemplateEngineError(f"Tag {{{{{tag}}}}} requires a target (use {{{{{tag}#ClassName}})")

    # Find the class
    class_data = None
    for cls in source_data.classes:
        if cls.name == target:
            class_data = cls
            break

    if class_data is None:
        raise TemplateEngineError(f"Class '{target}' not found in source")

    # Render based on tag
    if tag == 'class_name':
        return target

    if tag == 'class_short_description':
        return class_data.short_description or "No description"

    if tag == 'class_full_description':
        return class_data.full_description or "No description"

    if tag == 'class_info':
        return _render_class_info(class_data)

    if tag == 'properties':
        return _render_properties(class_data)

    if tag == 'public_methods':
        return _render_methods(class_data, 'public', source_data, folder_slug)

    if tag == 'private_methods':
        return _render_methods(class_data, 'private', source_data, folder_slug)

    if tag == 'static_methods':
        return _render_methods(class_data, 'static', source_data, folder_slug)

    if tag == 'class_methods':
        return _render_methods(class_data, 'classmethod', source_data, folder_slug)

    if tag == 'all_methods':
        return _render_methods(class_data, 'all', source_data, folder_slug)

    if tag == 'dunder_methods':
        return _render_methods(class_data, 'dunder', source_data, folder_slug)

    if tag == 'source_link':
        return f"{class_data.source_file}:{class_data.source_line}"

    if tag == 'decorators':
        return ", ".join(class_data.decorators) if class_data.decorators else ""

    if tag == 'base_classes':
        return ", ".join(class_data.base_classes) if class_data.base_classes else "(none)"

    if tag == 'methods_filtered':
        if not modifier:
            raise TemplateEngineError("methods_filtered requires a list of method names")
        method_names = [m.strip() for m in modifier.split(',')]
        return _render_methods_filtered(class_data, method_names, source_data, folder_slug)

    if tag == 'public_methods_except':
        if not modifier:
            raise TemplateEngineError("public_methods_except requires a list of method names to exclude")
        exclude_names = [m.strip() for m in modifier.split(',')]
        return _render_methods_public_except(class_data, exclude_names, source_data, folder_slug)

    if tag == 'public_methods_summary':
        return _render_methods_summary(class_data, 'public', folder_slug, current_output_path, source_data)

    if tag == 'private_methods_summary':
        return _render_methods_summary(class_data, 'private', folder_slug, current_output_path, source_data)

    if tag == 'methods_details':
        return _render_methods_details(class_data, source_data, folder_slug)

    raise TemplateEngineError(f"Unknown data tag: {{{{{tag}#{target}}}}}")


def render_data_tags(body: str, source_data: SourceData | None, folder_slug: str = "", current_output_path: str = "") -> str:
    """Replace all {{data_tag}} patterns in body with rendered content.

    Args:
        body: Template body with {{data_tag}} patterns.
        source_data: SourceData for looking up class/function info.
        folder_slug: Folder slug for generating class links.
        current_output_path: Output path of the current page being rendered.

    Returns:
        Body with data tags rendered.

    Raises:
        TemplateEngineError: If a tag or target is unknown.
    """
    def replace_tag(match):
        tag = match.group(1)
        target = match.group(2)  # could be None
        modifier = match.group(3)  # could be None (for .exclude or filtered)

        return render_data_tag(tag, target, modifier, source_data, folder_slug, current_output_path)

    return DATA_TAG_PATTERN.sub(replace_tag, body)


def _render_classes_table(source_data: SourceData, folder_slug: str = "") -> str:
    """Render HTML table of classes."""
    if not source_data.classes:
        return "<p>No classes found.</p>"

    rows = []
    for cls in source_data.classes:
        desc = cls.short_description or "No description"
        link_target = f"{folder_slug}/{cls.name}" if folder_slug else cls.name
        rows.append(f"<tr><td>[[{link_target}]]</td><td>{desc}</td></tr>")

    return f"<table class='classes-table'>\n<thead><tr><th>Class</th><th>Description</th></tr></thead>\n<tbody>\n{''.join(rows)}\n</tbody>\n</table>"


def _render_functions_table(source_data: SourceData) -> str:
    """Render HTML table of functions."""
    if not source_data.functions:
        return "<p>No functions found.</p>"

    rows = []
    for func in source_data.functions:
        sig = _render_function_signature(func)
        desc = func.short_description or "No description"
        rows.append(f"<tr><td>{sig}</td><td>{desc}</td></tr>")

    return f"<table class='functions-table'>\n<thead><tr><th>Function</th><th>Description</th></tr></thead>\n<tbody>\n{''.join(rows)}\n</tbody>\n</table>"


def _render_constants_table(source_data: SourceData) -> str:
    """Render HTML table of constants."""
    if not source_data.constants:
        return "<p>No constants found.</p>"

    rows = []
    for const in source_data.constants:
        rows.append(f"<tr><td>{const.name}</td><td>{const.value}</td><td>{const.type}</td></tr>")

    return f"<table class='constants-table'>\n<thead><tr><th>Name</th><th>Value</th><th>Type</th></tr></thead>\n<tbody>\n{''.join(rows)}\n</tbody>\n</table>"


def _render_class_info(class_data) -> str:
    """Render class info table."""
    import os
    rel_file = os.path.relpath(class_data.source_file).replace('\\', '/')
    module_name = os.path.splitext(os.path.basename(class_data.source_file))[0]
    return f"""<table class='class-info'>
<tr><td>Module:</td><td>{module_name}</td></tr>
<tr><td>File:</td><td>{rel_file}:{class_data.source_line}</td></tr>
<tr><td>Inherits:</td><td>{', '.join(class_data.base_classes) if class_data.base_classes else '(none)'}</td></tr>
</table>"""


def _render_properties(class_data) -> str:
    """Render properties table."""
    if not class_data.properties:
        return "<p>No properties.</p>"

    rows = []
    for prop in class_data.properties:
        rows.append(f"<tr><td>{prop.name}</td><td>{prop.type or 'Unknown'}</td><td>{prop.description}</td></tr>")

    return f"<table class='properties-table'>\n<thead><tr><th>Name</th><th>Type</th><th>Description</th></tr></thead>\n<tbody>\n{''.join(rows)}\n</tbody>\n</table>"


def _render_methods(class_data, method_type: str, source_data: SourceData | None = None, folder_slug: str = "") -> str:
    """Render methods table of specified type.

    Args:
        class_data: The class whose methods to render.
        method_type: 'public', 'private', 'static', 'classmethod', 'dunder', or 'all'.
        source_data: SourceData for linking types in signatures.
        folder_slug: Folder slug for generating cross-links.
    """
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

    if not methods:
        return "<p>No methods.</p>"

    rows = []
    for method in methods:
        sig = _render_function_signature(method, source_data, folder_slug)
        desc = method.short_description or "No description"
        rows.append(f"<tr><td id='{method.name}'>{sig}</td><td>{desc}</td></tr>")

    return f"<table class='methods-table'>\n<thead><tr><th>Signature</th><th>Description</th></tr></thead>\n<tbody>\n{''.join(rows)}\n</tbody>\n</table>"


def _render_methods_filtered(class_data, method_names: list[str], source_data: SourceData | None = None, folder_slug: str = "") -> str:
    """Render only specified methods in specified order.

    Args:
        class_data: The class whose methods to render.
        method_names: List of method names to include.
        source_data: SourceData for linking types in signatures.
        folder_slug: Folder slug for generating cross-links.
    """
    # Find methods by name
    methods = []
    for name in method_names:
        for method in class_data.methods:
            if method.name == name:
                methods.append(method)
                break

    if not methods:
        return "<p>No methods.</p>"

    rows = []
    for method in methods:
        sig = _render_function_signature(method, source_data, folder_slug)
        desc = method.short_description or "No description"
        rows.append(f"<tr><td id='{method.name}'>{sig}</td><td>{desc}</td></tr>")

    return f"<table class='methods-table'>\n<thead><tr><th>Signature</th><th>Description</th></tr></thead>\n<tbody>\n{''.join(rows)}\n</tbody>\n</table>"


def _render_methods_public_except(class_data, exclude_names: list[str], source_data: SourceData | None = None, folder_slug: str = "") -> str:
    """Render public methods except those in exclude_names.

    Args:
        class_data: The class whose methods to render.
        exclude_names: List of method names to exclude.
        source_data: SourceData for linking types in signatures.
        folder_slug: Folder slug for generating cross-links.
    """
    public_methods = []
    for method in class_data.methods:
        is_static = 'staticmethod' in method.decorators
        is_class = 'classmethod' in method.decorators
        is_private = method.name.startswith('_') and not method.name.startswith('__')
        is_dunder = method.name.startswith('__')

        # Skip non-public methods
        if is_private or is_dunder or is_static or is_class:
            continue
        # Skip excluded
        if method.name in exclude_names:
            continue
        public_methods.append(method)

    if not public_methods:
        return "<p>No methods.</p>"

    rows = []
    for method in public_methods:
        sig = _render_function_signature(method, source_data, folder_slug)
        desc = method.short_description or "No description"
        rows.append(f"<tr><td id='{method.name}'>{sig}</td><td>{desc}</td></tr>")

    return f"<table class='methods-table'>\n<thead><tr><th>Signature</th><th>Description</th></tr></thead>\n<tbody>\n{''.join(rows)}\n</tbody>\n</table>"


def _render_methods_summary(class_data, method_type: str, folder_slug: str = "", current_output_path: str = "", source_data: SourceData | None = None) -> str:
    """Render methods summary table with links to the detail section below.

    Args:
        class_data: The class whose methods to render.
        method_type: 'public' or 'private'.
        folder_slug: Folder slug for generating cross-links.
        current_output_path: Output path of the current page being rendered.
        source_data: SourceData for linking types in signatures.

    Returns:
        HTML table of method summaries with appropriate links.
    """
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
        methods.append(method)

    if not methods:
        return "<p>No methods.</p>"

    # Determine if we're on the same class page
    is_class_page = '-class.html' in current_output_path
    # Extract current class ID from path (e.g., "pipeline" from "pipeline-class.html")
    current_class_id = None
    if is_class_page:
        # Format is "ClassName-class.html" → extract "ClassName"
        basename = current_output_path.split('/')[-1]
        if basename.endswith('-class.html'):
            current_class_id = basename[:-10]  # Remove '-class.html'

    rows = []
    for method in methods:
        sig = _render_function_signature(method, source_data, folder_slug)
        desc_html = markdown_to_html(method.short_description or "No description")

        # Generate link based on context
        if is_class_page and current_class_id == class_data.name:
            # Same class page - use anchor
            link = f"<a href=\"#{method.name}\">{method.name}</a>"
        else:
            # Different page - use cross-link (resolve_links will convert [[...]] to <a>)
            link = f"[[{folder_slug}/{class_data.name}.{method.name}]]"

        rows.append(f"<tr><td>{link}{sig[len(method.name):]}</td><td>{desc_html}</td></tr>")

    return (f"<table class='methods-table'>\n"
            f"<thead><tr><th>Signature</th><th>Description</th></tr></thead>\n"
            f"<tbody>\n{''.join(rows)}\n</tbody>\n</table>")


def _render_methods_details(class_data, source_data: SourceData | None = None, folder_slug: str = "") -> str:
    """Render full detail blocks for public and private methods, combined.

    Args:
        class_data: The class whose methods to render.
        source_data: SourceData for linking types in signatures.
        folder_slug: Folder slug for generating cross-links.
    """
    methods = []
    for method in class_data.methods:
        is_static = 'staticmethod' in method.decorators
        is_class = 'classmethod' in method.decorators
        is_dunder = method.name.startswith('__')
        is_private = method.name.startswith('_') and not is_dunder
        is_public = not is_private and not is_dunder and not is_static and not is_class
        if is_public or is_private:
            methods.append(method)

    if not methods:
        return "<p>No methods.</p>"

    parts = []
    for method in methods:
        sig = _render_function_signature(method, source_data, folder_slug)
        anchor = method.name

        # Build method params with types for the header
        params_parts = []
        for arg in method.args:
            if arg.name == 'self':
                continue
            if arg.type:
                type_str = _link_type_if_class(arg.type, source_data, folder_slug)
                params_parts.append(f"{arg.name}: {type_str}")
            else:
                params_parts.append(arg.name)
        params_str = ", ".join(params_parts)

        html = f'<div class="method-detail">\n'
        html += f'<h3 id="{anchor}"><span class="method-name">{method.name}</span><span class="method-params">({params_str})</span></h3>\n'
        html += f'<div class="method-body">\n'

        desc = method.short_description
        if desc:
            desc_html = markdown_to_html(desc)
            html += f'{desc_html}\n'
        if method.full_description and method.full_description != method.short_description:
            # Strip leading whitespace from each line for proper markdown code blocks
            full_desc_stripped = '\n'.join(line.lstrip() for line in method.full_description.split('\n'))
            full_html = markdown_to_html(full_desc_stripped)
            html += f'{full_html}\n'

        if method.parameters:
            html += '<h4>Parameters</h4>\n'
            html += '<dl class="params-list">\n'
            for param in method.parameters:
                opt = " <em>(optional)</em>" if param.is_optional else ""
                html += f'<dd><code>{param.name}</code> — {param.description}{opt}</dd>\n'
            html += '</dl>\n'

        if method.returns:
            ret_type = method.returns.type or method.return_type or ""
            ret_desc = method.returns.description or ""
            if ret_type:
                type_str = _link_type_if_class(ret_type, source_data, folder_slug)
                html += f'<h4>Returns</h4>\n<div class="returns-block"><code>{type_str}</code> — {ret_desc}</div>\n'
            else:
                html += f'<h4>Returns</h4>\n<div class="returns-block">{ret_desc}</div>\n'
        elif method.return_type and method.return_type not in ('None', 'none'):
            type_str = _link_type_if_class(method.return_type, source_data, folder_slug)
            html += f'<h4>Returns</h4>\n<div class="returns-block"><code>{type_str}</code></div>\n'

        if method.raises:
            html += '<h4>Raises</h4>\n'
            html += '<dl class="raises-list">\n'
            for raise_doc in method.raises:
                type_str = _link_type_if_class(raise_doc.type, source_data, folder_slug)
                html += f'<dd><code>{type_str}</code> — {raise_doc.description}</dd>\n'
            html += '</dl>\n'

        html += '</div>\n'
        html += '</div>\n'
        parts.append(html)

    return '\n'.join(parts)


def _render_function_signature(func, source_data: SourceData | None = None, folder_slug: str = "") -> str:
    """Render a function signature as HTML.

    Args:
        func: The FunctionData to render.
        source_data: SourceData for linking type names to classes.
        folder_slug: Folder slug for generating cross-links.

    Returns:
        HTML string of the function signature.
    """
    args = []
    for arg in func.args:
        if arg.name == 'self':
            continue
        arg_str = arg.name
        if arg.type:
            type_str = _link_type_if_class(arg.type, source_data, folder_slug)
            arg_str = f"{arg_str}: {type_str}"
        if arg.default:
            arg_str = f"{arg_str}={arg.default}"
        args.append(arg_str)

    sig = f"{func.name}({', '.join(args)})"
    if func.return_type:
        type_str = _link_type_if_class(func.return_type, source_data, folder_slug)
        sig = f"{sig} -> {type_str}"

    return sig


def _link_type_if_class(type_str: str, source_data: SourceData | None, folder_slug: str) -> str:
    """Convert a type string to a cross-link if it's a class name.

    Args:
        type_str: The type string (e.g., 'BaseNode', 'List[int]', 'Optional[BaseNode]').
        source_data: SourceData for checking if a type is a class.
        folder_slug: Folder slug for generating cross-links.

    Returns:
        Linked or plain type string.
    """
    if not source_data or not folder_slug:
        return type_str

    # Extract class names from the type string
    class_names = _extract_class_names_from_type(type_str)

    if not class_names:
        return type_str

    # Check which class names exist in source_data
    result = type_str
    existing_class_names = {cls.name for cls in source_data.classes}

    for cls_name in class_names:
        if cls_name in existing_class_names:
            link = f"[[{folder_slug}/{cls_name}]]"
            result = result.replace(cls_name, link)

    return result


def _extract_class_names_from_type(type_str: str) -> list[str]:
    """Extract potential class names from a type annotation string.

    Handles:
    - Simple types: 'BaseNode' -> ['BaseNode']
    - Generics: 'List[BaseNode]' -> ['BaseNode']
    - Nested generics: 'Dict[str, MyClass]' -> ['MyClass']
    - Optional: 'Optional[BaseNode]' -> ['BaseNode']
    - Unions: 'Union[A, B]' -> ['A', 'B']
    - Nested: 'List[Optional[Dict[str, MyClass]]]' -> ['MyClass']

    Args:
        type_str: The type annotation string.

    Returns:
        List of potential class names found in the type.
    """
    import re

    # Find all bare names (not followed by [ or :) that start with uppercase
    # This avoids matching keywords like 'str', 'int', 'bool' but catches 'BaseNode', 'MyClass', etc.
    # However, we want to catch ALL uppercase-starting names as potential classes

    # Match identifiers: word characters including underscores
    # But we need to be careful about 'str', 'int', 'bool' etc - these are builtins

    # Simpler approach: find all ALL-CAPS or TitleCase identifiers
    # Classes are typically TitleCase or ALL_CAPS (for constants used as types)

    # Pattern to match potential class names (TitleCase or ALL_CAPS)
    pattern = r'\b([A-Z][a-zA-Z0-9_]*)\b'

    matches = re.findall(pattern, type_str)

    # Filter out common builtin types that aren't classes in our source
    # Actually, let's be inclusive - if it's a class in source_data, we'll link it

    return matches


def render_template(template_content: str, params: dict[str, str], source_data: SourceData | None, folder_slug: str = "", current_output_path: str = "") -> str:
    """Render a template with the given params and source data.

    Args:
        template_content: Raw .dtmpl template content.
        params: Dict of parameter values from node config.
        source_data: SourceData from the node's source folder (can be None).
        folder_slug: Folder slug for generating class links (e.g., 'dataflow').
        current_output_path: Output path of the current page being rendered.

    Returns:
        Rendered template string (may still have [[cross-links]] to resolve).

    Raises:
        TemplateEngineError: If required params are missing or invalid tags are used.
    """
    # Step 1: Parse and validate params
    required, optional, body = parse_params_block(template_content)

    # Merge optional params with defaults
    all_params = dict(optional)
    all_params.update(params)

    validate_params(required, all_params)

    # Step 2: %%PARAM%% substitution
    body = substitute_params(body, all_params)

    # Check for undeclared %%PARAM%% usage after substitution
    for match in SUBST_PATTERN.finditer(body):
        raise TemplateEngineError(f"Unknown param %%{match.group(1)}%%")

    # Step 3: :: for loop expansion
    body = expand_for_loops(body, source_data)

    # Step 4: {{data_tag}} rendering
    body = render_data_tags(body, source_data, folder_slug, current_output_path)

    return body
