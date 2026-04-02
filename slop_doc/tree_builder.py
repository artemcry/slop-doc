"""Stage 4: Tree Builder - builds the navigation tree from config files."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from slop_doc.sdoc_preprocessor import expand_macros, SDOCPreprocessorError
from slop_doc.parser import SourceData, parse_folder


class TreeBuilderError(Exception):
    """Raised when tree building fails."""
    pass


@dataclass
class Node:
    """Represents a node in the navigation tree."""
    title: str
    template: str
    params: dict[str, str] = field(default_factory=dict)
    source: str | None = None  # absolute path to source folder
    children: list[Node] = field(default_factory=list)
    output_path: str = ""  # relative path for output HTML file
    branch: str | None = None  # for .sdoc nodes, the branch path they attach to
    is_auto: bool = False  # True if generated from auto_source


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    # Replace spaces and special chars with hyphens
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.lower().strip('-')


def build_output_path(node: Node, parent_path: str = "") -> str:
    """Build output path for a node based on its position in the tree."""
    slug = slugify(node.title)
    if parent_path:
        path = f"{parent_path}/{slug}"
    else:
        path = slug
    return f"{path}.html"


def parse_main_config(config_path: str) -> dict[str, Any]:
    """Parse the main .sdoc.tree file."""
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return yaml.safe_load(content)


def parse_folder_config(config_path: str, source_folder: str, class_names: list[str] = None, function_names: list[str] = None) -> dict[str, Any]:
    """Parse a .sdoc file with macro expansion."""
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Expand macros
    try:
        expanded = expand_macros(content, class_names, function_names)
    except SDOCPreprocessorError as e:
        raise TreeBuilderError(f"Error preprocessing {config_path}: {e}")

    # Parse YAML
    try:
        return yaml.safe_load(expanded)
    except yaml.YAMLError as e:
        raise TreeBuilderError(f"Error parsing YAML in {config_path}: {e}")


def find_docs_configs(root_dir: str) -> list[tuple[str, str]]:
    """Find all .sdoc files in a directory tree.

    Returns:
        List of (config_path, source_folder) tuples.
    """
    configs = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if '.sdoc' in filenames:
            config_path = os.path.join(dirpath, '.sdoc')
            # Source folder is the directory containing the .sdoc
            source_folder = dirpath
            configs.append((config_path, source_folder))
    return configs


def parse_source_folder(source_folder: str) -> SourceData:
    """Parse all Python files in a source folder."""
    return parse_folder(source_folder)


def build_tree_from_config(tree_config: list[dict], templates_dir: str, parent_path: str = "") -> list[Node]:
    """Build a tree of Node objects from the tree: section of main config.

    Args:
        tree_config: List of tree node dicts from main config.
        templates_dir: Path to templates directory.
        parent_path: Parent path for output path generation.

    Returns:
        List of Node objects.
    """
    nodes = []
    for item in tree_config:
        title = item.get('title', '')
        template = item.get('template', '')
        params = item.get('params', {})
        children_config = item.get('children', [])

        node = Node(
            title=title,
            template=template,
            params=params
        )

        # Build output path
        node.output_path = build_output_path(node, parent_path)

        # Process children
        if children_config:
            child_path = f"{parent_path}/{slugify(title)}" if parent_path else slugify(title)
            node.children = build_tree_from_config(children_config, templates_dir, child_path)

        nodes.append(node)

    return nodes


def attach_auto_nodes(tree: list[Node], auto_nodes: list[Node], branch: str) -> None:
    """Attach auto-generated nodes to the correct branch in the tree.

    Args:
        tree: The current tree (modified in place).
        auto_nodes: Nodes to attach.
        branch: The branch path to attach to (e.g., "API Reference > Core").
    """
    branch_parts = [p.strip() for p in branch.split('>')]

    # Find the target parent node
    target = _find_node_by_branch(tree, branch_parts)
    if target is None:
        raise TreeBuilderError(f"Branch '{branch}' not found in main tree")

    # Attach auto_nodes as children
    target.children.extend(auto_nodes)


def _find_node_by_branch(tree: list[Node], branch_parts: list[str]) -> Node | None:
    """Find a node by its branch path.

    Args:
        tree: Current tree level to search.
        branch_parts: List of title parts to traverse.

    Returns:
        The found Node or None.
    """
    if not branch_parts:
        return None

    first_part = branch_parts[0]
    for node in tree:
        if node.title == first_part:
            if len(branch_parts) == 1:
                return node
            else:
                return _find_node_by_branch(node.children, branch_parts[1:])

    return None


def _node_path_prefix(output_path: str) -> str:
    """Strip .html extension to get a path prefix for children."""
    if output_path.endswith('.html'):
        return output_path[:-5]
    return output_path


def build_tree(config_path: str) -> tuple[list[Node], dict[str, SourceData]]:
    """Build the complete documentation tree.

    Args:
        config_path: Path to .sdoc.tree.

    Returns:
        Tuple of (root_nodes, source_data_by_folder)
        - root_nodes: List of root Node objects
        - source_data_by_folder: Dict mapping source folder paths to SourceData
    """
    config = parse_main_config(config_path)
    config_dir = os.path.dirname(os.path.abspath(config_path))
    templates_dir = os.path.join(config_dir, config.get('templates_dir', 'docs/templates/'))

    # Build manual tree first (without auto-generated nodes)
    tree_config = config.get('tree', [])
    root_nodes = build_tree_from_config(tree_config, templates_dir)

    source_data_by_folder: dict[str, SourceData] = {}

    # Find nodes with auto_source in the tree config and process them
    _find_and_process_auto_sources(
        tree_config, root_nodes, root_nodes, config_dir, templates_dir, source_data_by_folder
    )

    return root_nodes, source_data_by_folder


def _find_and_process_auto_sources(
    tree_config: list[dict],
    nodes: list[Node],
    root_nodes: list[Node],
    config_dir: str,
    templates_dir: str,
    source_data_by_folder: dict,
) -> None:
    """Recursively scan tree config for auto_source nodes and attach sub-trees."""
    for item, node in zip(tree_config, nodes):
        if 'auto_source' in item:
            auto_path = os.path.join(config_dir, item['auto_source'])
            _process_auto_source_path(auto_path, root_nodes, source_data_by_folder, templates_dir)

        children_config = item.get('children', [])
        if children_config and node.children:
            _find_and_process_auto_sources(
                children_config, node.children, root_nodes, config_dir, templates_dir, source_data_by_folder
            )


def _process_auto_source_path(
    auto_path: str,
    root_nodes: list[Node],
    source_data_by_folder: dict,
    templates_dir: str,
) -> None:
    """Scan direct subdirectories of auto_path for .sdoc files and attach sub-trees."""
    if not os.path.isdir(auto_path):
        return

    for item_name in sorted(os.listdir(auto_path)):
        item_path = os.path.join(auto_path, item_name)
        if not os.path.isdir(item_path):
            continue
        dcfg_path = os.path.join(item_path, '.sdoc')
        if not os.path.exists(dcfg_path):
            continue
        _process_single_dcfg(dcfg_path, item_path, root_nodes, source_data_by_folder, templates_dir)


def _process_single_dcfg(
    dcfg_path: str,
    source_folder: str,
    root_nodes: list[Node],
    source_data_by_folder: dict,
    templates_dir: str,
) -> None:
    """Parse a single .sdoc, build its sub-tree, and attach to the declared branch."""
    source_data = parse_source_folder(source_folder)
    source_data_by_folder[source_folder] = source_data

    class_names = [c.name for c in source_data.classes]
    function_names = [f.name for f in source_data.functions]

    folder_config = parse_folder_config(dcfg_path, source_folder, class_names, function_names)

    branch = folder_config.get('branch', '')
    if not branch:
        return

    branch_parts = [p.strip() for p in branch.split('>')]
    branch_node = _find_node_by_branch(root_nodes, branch_parts)
    if branch_node is None:
        raise TreeBuilderError(f"Branch '{branch}' not found in main tree")

    parent_prefix = _node_path_prefix(branch_node.output_path)

    title = folder_config.get('title', '')
    template = folder_config.get('template', 'default_module')

    folder_node = Node(
        title=title,
        template=template,
        params=folder_config.get('params', {}),
        source=source_folder,
        is_auto=True,
    )
    folder_node.output_path = build_output_path(folder_node, parent_prefix)

    children_config = folder_config.get('children', [])
    if children_config:
        child_prefix = _node_path_prefix(folder_node.output_path)
        folder_node.children = _build_children(children_config, source_folder, templates_dir, child_prefix)

    branch_node.children.append(folder_node)


def build_tree_from_folder_config(
    folder_config: dict[str, Any],
    source_folder: str,
    templates_dir: str,
    root_nodes: list[Node],
    parent_path: str = ""
) -> list[Node]:
    """Build a sub-tree from a folder's .sdoc config.

    Args:
        folder_config: Parsed .sdoc content.
        source_folder: Path to the source folder.
        templates_dir: Path to templates directory.
        root_nodes: Root nodes for finding branches.
        parent_path: Parent path for output path generation.

    Returns:
        List of Node objects for this folder.
    """
    title = folder_config.get('title', '')
    template = folder_config.get('template', 'default_module')
    branch = folder_config.get('branch')
    children_config = folder_config.get('children', [])

    node = Node(
        title=title,
        template=template,
        params=folder_config.get('params', {}),
        source=source_folder,
        branch=branch,
        is_auto=True
    )

    # Build output path
    node.output_path = build_output_path(node, parent_path)

    # Process children
    if children_config:
        child_path = f"{parent_path}/{slugify(title)}" if parent_path else slugify(title)
        node.children = _build_children(
            children_config,
            source_folder,
            templates_dir,
            child_path
        )

    return [node]


def _build_children(
    children_config: list[Any],
    source_folder: str,
    templates_dir: str,
    parent_path: str
) -> list[Node]:
    """Build child nodes from a children: list in .sdoc."""
    nodes = []

    for child in children_config:
        if isinstance(child, dict):
            if 'dir' in child:
                # Recurse into subfolder
                subfolder = os.path.join(source_folder, child['dir'])
                sub_configs = find_docs_configs(subfolder)
                for config_path, sf in sub_configs:
                    source_data = parse_source_folder(sf)
                    class_names = [c.name for c in source_data.classes]
                    function_names = [f.name for f in source_data.functions]
                    folder_config = parse_folder_config(config_path, sf, class_names, function_names)
                    sub_nodes = build_tree_from_folder_config(
                        folder_config, sf, templates_dir, [], parent_path
                    )
                    nodes.extend(sub_nodes)
            else:
                # Regular child node
                title = child.get('title', '')
                template = child.get('template', '')
                params = child.get('params', {})

                node = Node(
                    title=title,
                    template=template,
                    params=params,
                    source=source_folder  # Children inherit parent's source
                )
                node.output_path = build_output_path(node, parent_path)
                nodes.append(node)

    return nodes
