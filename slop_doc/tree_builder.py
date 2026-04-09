"""Tree Builder — builds the navigation tree from the docs folder structure.

The folder hierarchy IS the documentation tree.  Each ``.md`` file becomes a
page node; each folder with a ``root.md`` becomes a group node.  No
``.sdoc.tree`` or ``.sdoc`` files are involved.

Source folder inheritance:
    ``py_source`` set in a ``root.md`` front-matter is inherited by
    all ``.md`` siblings and by child folders (unless overridden by a deeper
    ``root.md``).
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

from slop_doc.frontmatter import parse_frontmatter, PageMeta, FrontmatterError
from slop_doc.parser import SourceData, parse_folder
from slop_doc.tag_renderer import expand_data_tags_in_list


class TreeBuilderError(Exception):
    """Raised when tree building fails."""
    pass


@dataclass
class Node:
    """Represents a node in the navigation tree."""
    title: str
    content: str = ""             # Markdown body (empty for auto-generated class pages)
    source: str | None = None     # absolute path to source folder
    children: list[Node] = field(default_factory=list)
    output_path: str = ""         # relative path for output HTML file
    is_auto: bool = False         # True if auto-generated (class/function page)
    auto_class: str | None = None # class name for auto-generated class pages
    auto_function: str | None = None  # function name for auto-generated function pages
    auto_source_file: str | None = None  # source file basename (no ext) for file-function pages
    order: int | None = None          # explicit sort order (lower = first)
    md_source_path: str | None = None  # absolute path to the .md file that generated this node
    meta: PageMeta = field(default_factory=PageMeta)


# ---------------------------------------------------------------------------
# Slug / path helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.lower().strip('-')


def _title_from_filename(filename: str) -> str:
    """Derive a human-readable title from a filename.

    Strips extension, leading numeric prefix, and cleans separators:
        ``1-getting_started.md`` → ``Getting Started``
        ``sOme__texT.md`` → ``Some Text``
    """
    name = os.path.splitext(filename)[0]
    # Strip leading numeric prefix (e.g. "1-", "02-")
    name = re.sub(r'^\d+[-._]\s*', '', name)
    # Replace separators (-, _, multiple spaces) with single space
    name = re.sub(r'[-_]+', ' ', name)
    # Title case each word
    return name.strip().title()


def _sort_key(filename: str) -> tuple:
    """Sort key: files with a leading number sort numerically, others alphabetically."""
    name = os.path.splitext(filename)[0]
    m = re.match(r'^(\d+)', name)
    if m:
        return (0, int(m.group(1)), name)
    return (1, 0, name)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_tree(docs_root: str, exclude_dirs: set[str] | None = None) -> tuple[list[Node], dict[str, SourceData]]:
    """Build the complete navigation tree from a docs folder.

    Args:
        docs_root: Path to the documentation root folder.
        exclude_dirs: Directory names to skip (e.g. {"build"}).

    Returns:
        Tuple of (root_nodes, source_data_by_folder).
    """
    source_data_cache: dict[str, SourceData] = {}
    path_base = os.path.dirname(os.path.abspath(docs_root))
    root_node = _walk_folder(docs_root, "", None, source_data_cache, path_base, is_root=True, exclude_dirs=exclude_dirs)

    if root_node is None:
        raise TreeBuilderError(f"No .md files found in {docs_root}")

    return root_node.children, source_data_cache


def build_tree_with_root(docs_root: str, exclude_dirs: set[str] | None = None) -> tuple[Node, dict[str, SourceData]]:
    """Like build_tree() but returns the root Node itself (used by builder for index.html).

    Returns:
        Tuple of (root_node, source_data_by_folder).
    """
    source_data_cache: dict[str, SourceData] = {}
    path_base = os.path.dirname(os.path.abspath(docs_root))
    root_node = _walk_folder(docs_root, "", None, source_data_cache, path_base, is_root=True, exclude_dirs=exclude_dirs)

    if root_node is None:
        raise TreeBuilderError(f"No .md files found in {docs_root}")

    return root_node, source_data_cache


# ---------------------------------------------------------------------------
# Recursive folder walk
# ---------------------------------------------------------------------------

def _walk_folder(
    folder_path: str,
    parent_output_prefix: str,
    inherited_source: str | None,
    source_data_cache: dict[str, SourceData],
    path_base: str = "",
    is_root: bool = False,
    exclude_dirs: set[str] | None = None,
) -> Node | None:
    """Walk a single folder and return a folder Node (or None if empty).

    Args:
        folder_path: Absolute path to the folder.
        parent_output_prefix: Output path prefix from parent (e.g., "api/core").
        inherited_source: py_source inherited from ancestor.
        source_data_cache: Shared cache of parsed SourceData.
        path_base: Project root (parent of docs root) for resolving relative paths.
        is_root: True for the top-level docs folder (children at top level).
        exclude_dirs: Set of directory names to skip (e.g. output dir).

    Returns:
        A folder Node with children, or None.
    """
    if not os.path.isdir(folder_path):
        return None

    # --- Read root.md if present ---
    root_md_path = os.path.join(folder_path, 'root.md')
    folder_meta = PageMeta()
    folder_body = ""

    if os.path.isfile(root_md_path):
        with open(root_md_path, 'r', encoding='utf-8') as f:
            raw = f.read()
        try:
            folder_meta, folder_body = parse_frontmatter(raw)
        except FrontmatterError as e:
            raise TreeBuilderError(f"Error in {root_md_path}: {e}")

    folder_title = folder_meta.title or _title_from_filename(os.path.basename(folder_path))

    # Resolve source folder for this level (relative to project root, not current folder)
    local_source = _resolve_source_folder(folder_meta.py_source, path_base, root_md_path)
    effective_source = local_source or inherited_source

    # Build output prefix for this folder
    if is_root:
        output_prefix = ""  # root level — children are at top level
    elif parent_output_prefix:
        output_prefix = f"{parent_output_prefix}/{slugify(folder_title)}"
    else:
        output_prefix = slugify(folder_title)

    # Create the folder node
    # If no root.md or root.md has no content — container node (no page, just a group in nav)
    has_root = os.path.isfile(root_md_path)
    has_content = bool(folder_body.strip())
    if has_root and has_content:
        folder_output_path = f"{output_prefix}/index.html" if output_prefix else ""
    else:
        folder_output_path = ""  # container node — no page generated

    folder_node = Node(
        title=folder_title,
        content=folder_body,
        source=effective_source,
        output_path=folder_output_path,
        order=folder_meta.order,
        md_source_path=os.path.abspath(root_md_path) if has_root else None,
        meta=folder_meta,
    )

    # --- Expand children generators from root.md front-matter ---
    if folder_meta.children and effective_source:
        _get_source_data(effective_source, source_data_cache)
        _expand_children(folder_node, folder_meta.children, effective_source, source_data_cache)

    # --- Collect and sort .md files (excluding root.md) ---
    md_files = []
    subdirs = []

    for entry in sorted(os.listdir(folder_path)):
        full = os.path.join(folder_path, entry)
        if os.path.isfile(full) and entry.endswith('.md') and entry != 'root.md':
            md_files.append(entry)
        elif os.path.isdir(full) and not entry.startswith('.') and entry != '__pycache__':
            if exclude_dirs and entry in exclude_dirs:
                continue
            subdirs.append(entry)

    md_files.sort(key=_sort_key)
    subdirs.sort(key=_sort_key)

    has_md_files = bool(md_files)

    # --- Process .md files ---
    for md_file in md_files:
        md_path = os.path.join(folder_path, md_file)
        child_nodes = _process_md_file(
            md_path, md_file, output_prefix, effective_source, path_base, source_data_cache
        )
        folder_node.children.extend(child_nodes)

    # --- Recurse into subdirectories ---
    for subdir in subdirs:
        sub_path = os.path.join(folder_path, subdir)
        sub_node = _walk_folder(sub_path, output_prefix, effective_source, source_data_cache, path_base, exclude_dirs=exclude_dirs)
        if sub_node is not None:
            folder_node.children.append(sub_node)

    # --- Sort children by explicit order (if any) ---
    # Nodes with order come first (sorted by order value),
    # then nodes without order keep their original position.
    _sort_by_order(folder_node.children)

    # --- Skip folders with no content at all ---
    if not has_root and not has_md_files and not folder_node.children:
        return None

    return folder_node


def _sort_by_order(children: list[Node]) -> None:
    """Stable-sort children: nodes with ``order`` first (ascending), rest keep position."""
    children.sort(key=lambda n: (0, n.order) if n.order is not None else (1, 0))


# ---------------------------------------------------------------------------
# Process a single .md file → one or more Nodes
# ---------------------------------------------------------------------------

def _process_md_file(
    md_path: str,
    filename: str,
    parent_output_prefix: str,
    inherited_source: str | None,
    path_base: str,
    source_data_cache: dict[str, SourceData],
) -> list[Node]:
    """Process a single .md file and return the resulting Node(s).

    If the file's front-matter contains ``children``, auto-generated child
    nodes (one per class/function) are created.
    """
    with open(md_path, 'r', encoding='utf-8') as f:
        raw = f.read()

    try:
        meta, body = parse_frontmatter(raw)
    except FrontmatterError as e:
        raise TreeBuilderError(f"Error in {md_path}: {e}")

    # Title: front-matter title > first heading > filename
    title = meta.title or _title_from_filename(filename)

    # Resolve source folder (relative to project root)
    local_source = _resolve_source_folder(meta.py_source, path_base, md_path)
    effective_source = local_source or inherited_source

    # Pre-populate source_data cache so {{classes}} can be expanded in body
    if effective_source:
        _get_source_data(effective_source, source_data_cache)

    # Output path
    slug = slugify(title)
    if parent_output_prefix:
        output_path = f"{parent_output_prefix}/{slug}.html"
    else:
        output_path = f"{slug}.html"

    node = Node(
        title=title,
        content=body,
        source=effective_source,
        output_path=output_path,
        order=meta.order,
        md_source_path=os.path.abspath(md_path),
        meta=meta,
    )

    # --- Handle children generators ---
    if meta.children:
        _expand_children(node, meta.children, effective_source, source_data_cache)

    return [node]


# ---------------------------------------------------------------------------
# Children expansion ({{classes}}, {{functions}} in children: block)
# ---------------------------------------------------------------------------

def _expand_children(
    parent_node: Node,
    children_spec: dict,
    effective_source: str | None,
    source_data_cache: dict[str, SourceData],
) -> None:
    """Expand children: block in front-matter.

    children_spec is a dict like:
        {"classes": "{{classes}}", "functions": ["{{functions}}", "extra_func"]}
    or:
        {"classes": ["ClassA", "{{classes}}", "ClassB"]}

    Each class entry generates a child Node with auto_class set.
    Each function entry generates a child Node with auto_function set.
    """
    if effective_source is None:
        raise TreeBuilderError(
            f"Node '{parent_node.title}' has children generators but no source folder is set"
        )

    # Parse source data
    source_data = _get_source_data(effective_source, source_data_cache)

    parent_prefix = parent_node.output_path.replace('.html', '')

    # Process each child type
    for child_type, spec in children_spec.items():
        if isinstance(spec, str):
            spec = [spec]
        if not isinstance(spec, list):
            continue

        names = expand_data_tags_in_list(spec, source_data)

        # All class-like types generate auto_class nodes
        CLASS_TYPES = {'classes', 'enums', 'dataclasses', 'interfaces', 'protocols', 'exceptions', 'plain_classes'}

        if child_type == 'functions':
            # Individual function nodes in the nav tree, each linking to
            # the file-function page with an anchor: file-page.html#func_name
            func_map = {f.name: f for f in source_data.functions}
            for name in names:
                func = func_map.get(name)
                if func and func.source_file:
                    file_base = os.path.splitext(os.path.basename(func.source_file))[0]
                else:
                    file_base = '_unknown'
                file_slug = slugify(file_base)
                child = Node(
                    title=name,
                    content="",
                    source=effective_source,
                    output_path=f"{parent_prefix}/{file_slug}.html#{name}",
                    is_auto=True,
                    auto_function=name,
                    auto_source_file=file_base,
                )
                parent_node.children.append(child)
            continue

        for name in names:
            slug = slugify(name)

            if child_type in CLASS_TYPES:
                child = Node(
                    title=f"{name}",
                    content="",
                    source=effective_source,
                    output_path=f"{parent_prefix}/{slug}.html",
                    is_auto=True,
                    auto_class=name,
                )
            else:
                continue

            parent_node.children.append(child)


# ---------------------------------------------------------------------------
# Source folder resolution
# ---------------------------------------------------------------------------

def _resolve_source_folder(raw_path: str | None, path_base: str, context_file: str = "") -> str | None:
    """Resolve a py_source path relative to the project root.

    All relative paths in .md files are resolved against *path_base* (the
    parent directory of the docs root), NOT against the .md file's own folder.
    This means the same path string works identically regardless of how deep
    in the docs tree the .md file sits.

    Args:
        raw_path: The path string from front-matter (may be relative or absolute).
        path_base: Project root — parent of the docs root folder.
        context_file: Path to the .md file (for error messages only).
    """
    if not raw_path:
        return None
    if os.path.isabs(raw_path):
        resolved = raw_path
    else:
        resolved = os.path.normpath(os.path.join(path_base, raw_path))
    if os.path.isdir(resolved):
        return resolved
    raise TreeBuilderError(
        f"py_source '{raw_path}' resolved to '{resolved}' "
        f"which does not exist (in {context_file or 'unknown file'})"
    )


def _get_source_data(source_folder: str, cache: dict[str, SourceData]) -> SourceData:
    """Get (or parse & cache) SourceData for a source folder."""
    if source_folder not in cache:
        cache[source_folder] = parse_folder(source_folder)
    return cache[source_folder]


# ---------------------------------------------------------------------------
# Heading extraction
# ---------------------------------------------------------------------------

def _extract_first_heading(body: str) -> str | None:
    """Extract the first Markdown heading from body text."""
    m = re.search(r'^#\s+(.+)$', body, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return None
