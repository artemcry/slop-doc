"""Stage 3: Template Engine - processes .dtmpl template files."""

from __future__ import annotations

import re
from typing import Any

from pydocgen.parser import SourceData


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


def render_data_tag(tag: str, target: str | None, modifier: str | None, source_data: SourceData | None, folder_slug: str = "") -> str:
    """Render a {{data_tag}} or {{data_tag#target}} tag.

    Args:
        tag: The tag name (e.g., "classes", "public_methods").
        target: The target name if present (e.g., "Pipeline").
        modifier: Optional modifier (e.g., "run,stop" for methods_filtered).
        source_data: SourceData for looking up class/function info.
        folder_slug: Folder slug for generating class links.

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
        return _render_methods(class_data, 'public')

    if tag == 'private_methods':
        return _render_methods(class_data, 'private')

    if tag == 'static_methods':
        return _render_methods(class_data, 'static')

    if tag == 'class_methods':
        return _render_methods(class_data, 'classmethod')

    if tag == 'all_methods':
        return _render_methods(class_data, 'all')

    if tag == 'dunder_methods':
        return _render_methods(class_data, 'dunder')

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
        return _render_methods_filtered(class_data, method_names)

    if tag == 'public_methods_except':
        if not modifier:
            raise TemplateEngineError("public_methods_except requires a list of method names to exclude")
        exclude_names = [m.strip() for m in modifier.split(',')]
        return _render_methods_public_except(class_data, exclude_names)

    if tag == 'public_methods_summary':
        return _render_methods_summary(class_data, 'public')

    if tag == 'private_methods_summary':
        return _render_methods_summary(class_data, 'private')

    if tag == 'methods_details':
        return _render_methods_details(class_data)

    raise TemplateEngineError(f"Unknown data tag: {{{{{tag}#{target}}}}}")


def render_data_tags(body: str, source_data: SourceData | None, folder_slug: str = "") -> str:
    """Replace all {{data_tag}} patterns in body with rendered content.

    Args:
        body: Template body with {{data_tag}} patterns.
        source_data: SourceData for looking up class/function info.
        folder_slug: Folder slug for generating class links.

    Returns:
        Body with data tags rendered.

    Raises:
        TemplateEngineError: If a tag or target is unknown.
    """
    def replace_tag(match):
        tag = match.group(1)
        target = match.group(2)  # could be None
        modifier = match.group(3)  # could be None (for .exclude or filtered)

        return render_data_tag(tag, target, modifier, source_data, folder_slug)

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


def _render_methods(class_data, method_type: str) -> str:
    """Render methods table of specified type."""
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
        sig = _render_function_signature(method)
        desc = method.short_description or "No description"
        rows.append(f"<tr><td id='{method.name}'>{sig}</td><td>{desc}</td></tr>")

    return f"<table class='methods-table'>\n<thead><tr><th>Signature</th><th>Description</th></tr></thead>\n<tbody>\n{''.join(rows)}\n</tbody>\n</table>"


def _render_methods_filtered(class_data, method_names: list[str]) -> str:
    """Render only specified methods in specified order."""
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
        sig = _render_function_signature(method)
        desc = method.short_description or "No description"
        rows.append(f"<tr><td id='{method.name}'>{sig}</td><td>{desc}</td></tr>")

    return f"<table class='methods-table'>\n<thead><tr><th>Signature</th><th>Description</th></tr></thead>\n<tbody>\n{''.join(rows)}\n</tbody>\n</table>"


def _render_methods_public_except(class_data, exclude_names: list[str]) -> str:
    """Render public methods except those in exclude_names."""
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
        sig = _render_function_signature(method)
        desc = method.short_description or "No description"
        rows.append(f"<tr><td id='{method.name}'>{sig}</td><td>{desc}</td></tr>")

    return f"<table class='methods-table'>\n<thead><tr><th>Signature</th><th>Description</th></tr></thead>\n<tbody>\n{''.join(rows)}\n</tbody>\n</table>"


def _render_methods_summary(class_data, method_type: str) -> str:
    """Render methods summary table with links to the detail section below."""
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

    rows = []
    for method in methods:
        sig = _render_function_signature(method)
        desc = method.short_description or "No description"
        anchor = method.name
        rows.append(f"<tr><td><a href=\"#{anchor}\">{method.name}</a>{sig[len(method.name):]}</td><td>{desc}</td></tr>")

    return (f"<table class='methods-table'>\n"
            f"<thead><tr><th>Signature</th><th>Description</th></tr></thead>\n"
            f"<tbody>\n{''.join(rows)}\n</tbody>\n</table>")


def _render_methods_details(class_data) -> str:
    """Render full detail blocks for public and private methods, combined."""
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
        sig = _render_function_signature(method)
        anchor = method.name

        html = f'<div class="method-detail">\n'
        html += f'<h3 id="{anchor}"><span class="method-name">{method.name}</span><span class="method-params">({", ".join(a.name for a in method.args if a.name != "self")})</span></h3>\n'
        html += f'<div class="method-body">\n'

        desc = method.short_description
        if desc:
            html += f'<p>{desc}</p>\n'

        if method.parameters:
            rows = []
            for param in method.parameters:
                type_str = param.type or "—"
                opt = " <em>(optional)</em>" if param.is_optional else ""
                rows.append(
                    f"<tr><td><code>{param.name}</code></td>"
                    f"<td>{type_str}</td><td>{param.description}{opt}</td></tr>"
                )
            html += (f"<table class='params-table'>\n"
                     f"<thead><tr><th>Parameter</th><th>Type</th><th>Description</th></tr></thead>\n"
                     f"<tbody>\n{''.join(rows)}\n</tbody>\n</table>\n")

        if method.returns:
            ret_type = method.returns.type or method.return_type or ""
            type_str = f" <code>{ret_type}</code>" if ret_type else ""
            html += f"<div class='returns-block'><strong>Returns</strong>{type_str} — {method.returns.description}</div>\n"
        elif method.return_type and method.return_type not in ('None', 'none'):
            html += f"<div class='returns-block'><strong>Returns</strong> <code>{method.return_type}</code></div>\n"

        if method.raises:
            rows = []
            for raise_doc in method.raises:
                rows.append(
                    f"<tr><td><code>{raise_doc.type}</code></td>"
                    f"<td>{raise_doc.description}</td></tr>"
                )
            html += (f"<table class='raises-table'>\n"
                     f"<thead><tr><th>Raises</th><th>Description</th></tr></thead>\n"
                     f"<tbody>\n{''.join(rows)}\n</tbody>\n</table>\n")

        html += '</div>\n'
        html += '</div>\n'
        parts.append(html)

    return '\n'.join(parts)


def _render_function_signature(func) -> str:
    """Render a function signature as HTML."""
    args = []
    for arg in func.args:
        if arg.name == 'self':
            continue
        arg_str = arg.name
        if arg.type:
            arg_str = f"{arg_str}: {arg.type}"
        if arg.default:
            arg_str = f"{arg_str}={arg.default}"
        args.append(arg_str)

    sig = f"{func.name}({', '.join(args)})"
    if func.return_type:
        sig = f"{sig} -> {func.return_type}"

    return sig


def render_template(template_content: str, params: dict[str, str], source_data: SourceData | None, folder_slug: str = "") -> str:
    """Render a template with the given params and source data.

    Args:
        template_content: Raw .dtmpl template content.
        params: Dict of parameter values from node config.
        source_data: SourceData from the node's source folder (can be None).
        folder_slug: Folder slug for generating class links (e.g., 'dataflow').

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
    body = render_data_tags(body, source_data, folder_slug)

    return body
