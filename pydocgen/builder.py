"""Stage 8: Build Orchestrator - orchestrates the full documentation build."""

from __future__ import annotations

import os
import sys
import argparse

from pydocgen.tree_builder import build_tree, Node, TreeBuilderError
from pydocgen.template_engine import render_template, TemplateEngineError
from pydocgen.cross_links import build_index, resolve_links, CrossLinkError, _get_folder_slug
from pydocgen.markdown_renderer import markdown_to_html
from pydocgen.layout import assemble_page, copy_assets, generate_search_index


class BuildError(Exception):
    """Raised when the build fails."""
    pass


def build_docs(config_path: str) -> None:
    """Build all documentation.

    Args:
        config_path: Path to docs_config.dcfg.

    Raises:
        BuildError: If the build fails.
    """
    try:
        # Step 1: Parse config and build tree
        tree, source_data_by_folder = build_tree(config_path)

        # Get config info for templates
        config_dir = os.path.dirname(os.path.abspath(config_path))
        from pydocgen.tree_builder import parse_main_config
        config = parse_main_config(config_path)

        project_name = config.get('project_name', 'Documentation')
        version = config.get('version', '')
        output_dir = os.path.join(config_dir, config.get('output_dir', 'build/docs/'))
        templates_dir = os.path.join(config_dir, config.get('templates_dir', 'docs/templates/'))
        assets_dir = os.path.join(config_dir, config.get('assets_dir', 'docs/assets/'))

        # Step 2: Build cross-link index
        index = build_index(tree, source_data_by_folder)

        # Step 3: Process each node
        pages_built = 0
        for node in _iterate_nodes(tree):
            # Skip container nodes without a template
            if not node.template:
                continue

            try:
                # Load template
                template_path = os.path.join(templates_dir, f"{node.template}.dtmpl")
                if not os.path.exists(template_path):
                    raise BuildError(f"Node '{node.title}': template '{node.template}' not found in {templates_dir}/")

                with open(template_path, 'r', encoding='utf-8') as f:
                    template_content = f.read()

                # Get source data for this node
                source_data = None
                if node.source and node.source in source_data_by_folder:
                    source_data = source_data_by_folder[node.source]

                # Compute folder_slug for class links (e.g., 'dataflow' from 'api-reference/dataflow.html')
                # Use node.source to get the correct folder, not output_path (which may be a child page)
                folder_slug = _get_folder_slug(node.output_path)
                if node.source:
                    # Derive folder from source path (e.g., '/path/to/src/dataflow' -> 'dataflow')
                    folder_slug = os.path.basename(node.source.rstrip('/'))

                # Render template (Step 6 part 1)
                rendered = render_template(template_content, node.params, source_data, folder_slug, node.output_path)

                # Convert markdown to HTML (Step 6 part 2)
                html_content = markdown_to_html(rendered)

                # Resolve cross-links (Step 6 part 3)
                html_content = resolve_links(html_content, index, node.output_path)

                # Assemble page (Step 7)
                page_html = assemble_page(html_content, node, tree, project_name, version)

                # Write output
                output_path = os.path.join(output_dir, node.output_path)
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(page_html)

                pages_built += 1

            except (TemplateEngineError, CrossLinkError) as e:
                raise BuildError(f"Node '{node.title}': {e}")

        # Step 4: Generate search index
        search_index = generate_search_index(tree, source_data_by_folder)
        search_index_path = os.path.join(output_dir, 'search_index.json')
        with open(search_index_path, 'w', encoding='utf-8') as f:
            f.write(search_index)

        # Step 5: Copy assets
        copy_assets(assets_dir, output_dir)

        print(f"Built {pages_built} pages to {output_dir}")

    except TreeBuilderError as e:
        raise BuildError(f"Config error: {e}")


def _iterate_nodes(tree: list[Node]) -> list[Node]:
    """Iterate all nodes in tree (flattened).

    Args:
        tree: The navigation tree.

    Returns:
        List of all nodes.
    """
    nodes = []
    for node in tree:
        nodes.append(node)
        if node.children:
            nodes.extend(_iterate_nodes(node.children))
    return nodes


def main() -> int:
    """Main CLI entry point.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    parser = argparse.ArgumentParser(description='PyDocGen - Static documentation generator')
    parser.add_argument('command', choices=['build'], help='Command to run')
    parser.add_argument('--config', default='docs_config.dcfg', help='Path to config file')

    args = parser.parse_args()

    if args.command == 'build':
        try:
            build_docs(args.config)
            return 0
        except BuildError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            return 1

    return 0
