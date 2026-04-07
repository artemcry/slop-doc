"""Front-matter parser for .md documentation files.

Parses JSON front-matter blocks at the top of .md files.
The front-matter is enclosed in curly braces {} and supports
relaxed JSON (comments with // and trailing commas).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


class FrontmatterError(Exception):
    """Raised when front-matter parsing fails."""
    pass


@dataclass
class PageMeta:
    """Parsed metadata from a .md file's front-matter."""
    title: str = ""
    default_source_folder: str | None = None
    children: dict | None = None  # {"classes": [...], "functions": [...]}
    order: int | None = None      # explicit sort order (lower = first)
    raw: dict = field(default_factory=dict)


def parse_frontmatter(content: str) -> tuple[PageMeta, str]:
    """Parse front-matter and body from a .md file.

    If the file starts with '{', everything up to the matching '}'
    is treated as relaxed JSON front-matter. The rest is Markdown body.

    Args:
        content: Raw file content.

    Returns:
        Tuple of (PageMeta, body_markdown).

    Raises:
        FrontmatterError: If the front-matter block is malformed.
    """
    stripped = content.lstrip()

    if not stripped.startswith('{'):
        # No front-matter — entire content is body
        return PageMeta(), content

    # Find the matching closing brace
    brace_end = _find_matching_brace(stripped)
    if brace_end == -1:
        raise FrontmatterError("Unclosed front-matter block: missing '}'")

    json_block = stripped[:brace_end + 1]
    body = stripped[brace_end + 1:].lstrip('\n')

    # Clean the JSON: remove comments and trailing commas
    clean_json = _clean_relaxed_json(json_block)

    try:
        data = json.loads(clean_json)
    except json.JSONDecodeError as e:
        raise FrontmatterError(f"Invalid front-matter JSON: {e}")

    if not isinstance(data, dict):
        raise FrontmatterError("Front-matter must be a JSON object")

    order_raw = data.get('order')
    order = int(order_raw) if order_raw is not None else None

    meta = PageMeta(
        title=data.get('title', ''),
        default_source_folder=data.get('default_source_folder'),
        children=data.get('children'),
        order=order,
        raw=data,
    )

    return meta, body


def _find_matching_brace(text: str) -> int:
    """Find the index of the closing brace matching the opening one at index 0.

    Handles nested braces and skips braces inside strings.

    Returns:
        Index of matching '}', or -1 if not found.
    """
    depth = 0
    in_string = False
    escape_next = False

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue

        if ch == '\\' and in_string:
            escape_next = True
            continue

        if ch == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i

    return -1


def _clean_relaxed_json(text: str) -> str:
    """Clean relaxed JSON by removing comments and trailing commas.

    Handles:
        - // line comments (outside strings)
        - # line comments (outside strings)
        - Trailing commas before } or ]
        - Unquoted keys (wraps them in quotes)
    """
    result = []
    i = 0
    in_string = False
    escape_next = False

    while i < len(text):
        ch = text[i]

        if escape_next:
            result.append(ch)
            escape_next = False
            i += 1
            continue

        if ch == '\\' and in_string:
            result.append(ch)
            escape_next = True
            i += 1
            continue

        if ch == '"':
            in_string = not in_string
            result.append(ch)
            i += 1
            continue

        if in_string:
            result.append(ch)
            i += 1
            continue

        # Outside string: check for comments
        if ch == '/' and i + 1 < len(text) and text[i + 1] == '/':
            # Skip to end of line
            end = text.find('\n', i)
            if end == -1:
                break
            i = end
            continue

        if ch == '#':
            # Skip to end of line
            end = text.find('\n', i)
            if end == -1:
                break
            i = end
            continue

        result.append(ch)
        i += 1

    cleaned = ''.join(result)

    # Remove trailing commas before } or ]
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)

    # Handle unquoted keys: word characters before a colon
    # Match patterns like { key: or , key: where key is not already quoted
    cleaned = re.sub(
        r'(?<=[{,\n])\s*([a-zA-Z_]\w*)\s*:',
        lambda m: f' "{m.group(1)}":',
        cleaned
    )

    return cleaned
