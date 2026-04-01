"""Stage 5: Cross-Link Index & Resolver - builds cross-reference index and resolves links."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydocgen.tree_builder import Node
    from pydocgen.parser import SourceData


class CrossLinkError(Exception):
    """Raised when cross-link resolution fails."""
    pass


# Pattern to match [[Target]] or [[Target|display text]] or [[Target.method]]
CROSS_LINK_PATTERN = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]')


@dataclass
class LinkTarget:
    """Represents a resolved link target."""
    url: str
    anchor: str | None = None


class CrossLinkIndex:
    """Global index for cross-reference resolution."""

    def __init__(self):
        # Short name → list of (url, display_name, module_path)
        self.short_index: dict[str, list[tuple[str, str, str]]] = {}
        # Fully qualified name → url
        self.qualified_index: dict[str, str] = {}
        # Module path for disambiguation
        self.module_paths: dict[str, str] = {}  # node_path → module_name
        # Folder/class index: "folder/ClassName" → url
        # e.g., "dataflow/Pipeline" → "api-reference/dataflow/pipeline-class.html"
        self.folder_class_index: dict[str, str] = {}

    def add_node(self, node: Node, source_data: SourceData | None = None) -> None:
        """Add a node to the index.

        Args:
            node: The node to add.
            source_data: Optional SourceData for extracting class/function names.
        """
        url = node.output_path

        # Add class names
        if source_data:
            for cls in source_data.classes:
                # Fully qualified: module.ClassName
                module_name = node.title
                fq_name = f"{module_name}.{cls.name}" if module_name else cls.name

                self.qualified_index[fq_name] = url

                # Short name with module context for disambiguation
                key = (cls.name, module_name)
                if cls.name not in self.short_index:
                    self.short_index[cls.name] = []
                self.short_index[cls.name].append((url, cls.name, module_name))

                # Add method names: ClassName.method (URL without anchor, anchor added by resolve)
                for method in cls.methods:
                    method_key = f"{cls.name}.{method.name}"
                    self.qualified_index[method_key] = url
                    self.short_index[method.name] = self.short_index.get(method.name, [])
                    self.short_index[method.name].append((url, method.name, module_name))

            # Add function names
            for func in source_data.functions:
                fq_name = f"{node.title}.{func.name}" if node.title else func.name
                self.qualified_index[fq_name] = url

                if func.name not in self.short_index:
                    self.short_index[func.name] = []
                self.short_index[func.name].append((url, func.name, node.title))

        # Add node title itself
        if node.title:
            self.short_index[node.title] = self.short_index.get(node.title, [])
            self.short_index[node.title].append((url, node.title, node.title))

    def resolve(self, target: str) -> LinkTarget:
        """Resolve a link target to a URL.

        Args:
            target: The link target in "folder/ClassName" or "folder/ClassName.method" format.

        Returns:
            LinkTarget with URL and optional anchor.

        Raises:
            CrossLinkError: If target is not found or invalid format.
        """
        # Require "folder/ClassName" or "folder/ClassName.method" format
        if '/' not in target:
            raise CrossLinkError(
                f"Invalid cross-link format '{target}'. Use 'folder/ClassName' or 'folder/ClassName.method' syntax."
            )

        # Split into class path and optional method
        method_name = None
        if '.' in target:
            class_path, method_name = target.rsplit('.', 1)
        else:
            class_path = target

        # Look up folder/class in index
        if class_path not in self.folder_class_index:
            raise CrossLinkError(f"Cross-link target '{class_path}' not found in index")

        url = self.folder_class_index[class_path]
        return LinkTarget(url=url, anchor=method_name)


def resolve_links(text: str, index: CrossLinkIndex, current_page: str = "") -> str:
    """Resolve [[Target]] patterns in text to HTML links.

    Args:
        text: Text containing [[Target]] patterns.
        index: CrossLinkIndex for resolving targets.
        current_page: Output path of the current page (for relative link计算).

    Returns:
        Text with [[Target]] replaced by <a href> tags.

    Raises:
        CrossLinkError: If a target cannot be resolved.
    """
    def replace_link(match):
        target = match.group(1).strip()
        display_text = match.group(2)  # Could be None for [[Target]]

        try:
            link = index.resolve(target)
            if link.anchor:
                href = f"{link.url}#{link.anchor}"
            else:
                href = link.url

            # Compute relative path if both paths are under output root
            if current_page and href:
                href = _compute_relative_path(current_page, href)

            if display_text:
                return f'<a href="{href}">{display_text}</a>'
            else:
                # Extract just the name after '/' for display
                display = target.rsplit('/', 1)[-1] if '/' in target else target
                return f'<a href="{href}">{display}</a>'
        except CrossLinkError as e:
            raise CrossLinkError(f"Error resolving link [[{target}]]: {e}")

    return CROSS_LINK_PATTERN.sub(replace_link, text)


def _compute_relative_path(from_path: str, to_path: str) -> str:
    """Compute relative path from one page to another.

    Args:
        from_path: Source page path (e.g., "api-reference/dataflow.html")
        to_path: Target page path (e.g., "api-reference/dataflow/pipeline-class.html")

    Returns:
        Relative path (e.g., "dataflow/pipeline-class.html")
    """
    import os

    # Normalize paths
    from_dir = os.path.dirname(from_path)
    to_dir = os.path.dirname(to_path)

    # Compute relative path
    rel = os.path.relpath(to_path, from_dir)
    # Convert backslashes to forward slashes for URL
    return rel.replace('\\', '/')


def _get_folder_slug(output_path: str) -> str:
    """Extract folder slug from output path.

    For 'api-reference/dataflow.html' returns 'dataflow'.
    For 'api-reference/dataflow/pipeline-class.html' returns 'dataflow'.
    For 'introduction.html' returns ''.

    Returns:
        Folder slug like 'dataflow' or empty string.
    """
    import os
    # Remove .html and split
    base = output_path.replace('.html', '')
    parts = base.split('/')

    # Check if this is a class page like 'folder/ClassName-class.html'
    if len(parts) >= 2 and parts[-1].endswith('-class'):
        return parts[-2]

    # For module pages like 'api-reference/dataflow.html'
    if len(parts) >= 2:
        return parts[-1]

    # For root pages like 'introduction.html'
    return ''


def build_index(tree: list[Node], source_data_by_folder: dict[str, SourceData]) -> CrossLinkIndex:
    """Build the global cross-link index from the tree.

    Args:
        tree: The navigation tree.
        source_data_by_folder: Dict mapping source folder paths to SourceData.

    Returns:
        CrossLinkIndex with all targets indexed.
    """
    index = CrossLinkIndex()

    # Track which sources have been indexed (to avoid duplicate indexing)
    indexed_sources: set[str] = set()

    def process_node(node: Node, parent_source: str | None = None):
        # Skip child class pages - they inherit parent's source
        # but we handle them specially below
        is_child_class_page = (
            node.template == 'default_class' and
            node.source == parent_source
        )

        if is_child_class_page:
            # For child class pages, add class and methods with this page's URL
            class_id = node.params.get('CLASS_ID', '')
            if class_id and node.source and node.source in source_data_by_folder:
                source_data = source_data_by_folder[node.source]
                # Find the class in source_data
                for cls in source_data.classes:
                    if cls.name == class_id:
                        # Compute folder slug: 'dataflow' from 'api-reference/dataflow/pipeline-class.html'
                        folder_slug = _get_folder_slug(node.output_path)
                        folder_class_key = f"{folder_slug}/{class_id}"
                        index.folder_class_index[folder_class_key] = node.output_path

                        # Also add method entries to folder_class_index
                        for method in cls.methods:
                            method_key = f"{folder_slug}/{class_id}.{method.name}"
                            index.folder_class_index[method_key] = node.output_path

                        # Also add to short_index for backward compatibility
                        index.short_index[class_id] = [(node.output_path, class_id, node.title)]
                        # Add method links pointing to this page (URL without anchor, anchor added by resolve)
                        for method in cls.methods:
                            method_key = f"{class_id}.{method.name}"
                            index.qualified_index[method_key] = node.output_path
                            index.short_index[method.name] = [(node.output_path, method.name, node.title)]
                        break
        else:
            # Get source data for this node
            source_data = None
            if node.source and node.source in source_data_by_folder:
                # Only index source_data if this source hasn't been indexed yet
                if node.source not in indexed_sources:
                    source_data = source_data_by_folder[node.source]
                    indexed_sources.add(node.source)

            # Add folder_class_index entries for module nodes with source_data
            if source_data:
                folder_slug = _get_folder_slug(node.output_path)
                if folder_slug:
                    for cls in source_data.classes:
                        folder_class_key = f"{folder_slug}/{cls.name}"
                        index.folder_class_index[folder_class_key] = node.output_path
                        for method in cls.methods:
                            method_key = f"{folder_slug}/{cls.name}.{method.name}"
                            index.folder_class_index[method_key] = node.output_path

            index.add_node(node, source_data)

        # Process children
        for child in node.children:
            process_node(child, node.source)

    for root_node in tree:
        process_node(root_node, None)

    return index
