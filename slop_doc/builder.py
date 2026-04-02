"""Stage 8: Build Orchestrator - orchestrates the full documentation build."""

from __future__ import annotations

import os
import sys
import argparse
import importlib.resources

from slop_doc.tree_builder import build_tree, Node, TreeBuilderError
from slop_doc.template_engine import render_template, TemplateEngineError
from slop_doc.cross_links import build_index, resolve_links, CrossLinkError, _get_folder_slug, CrossLinkIndex
from slop_doc.markdown_renderer import markdown_to_html
from slop_doc.layout import assemble_page, generate_search_index


class BuildError(Exception):
    """Raised when the build fails."""
    pass


def _copy_assets_with_defaults(assets_dir: str, output_dir: str, defaults_dir: str) -> None:
    """Copy assets to output directory.

    If assets_dir has no style.css, falls back to defaults/style.css.
    Always copies search.js from defaults.

    Args:
        assets_dir: Source assets directory (user-specified).
        output_dir: Destination directory.
        defaults_dir: Path to slop_doc/defaults directory.
    """
    import shutil

    output_assets = os.path.join(output_dir, 'assets')
    if os.path.exists(output_assets):
        shutil.rmtree(output_assets)

    os.makedirs(output_assets, exist_ok=True)

    # Copy user's assets if they exist
    if os.path.exists(assets_dir):
        for item in os.listdir(assets_dir):
            src = os.path.join(assets_dir, item)
            dst = os.path.join(output_assets, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

    # Ensure style.css exists (fall back to defaults if needed)
    style_css_dest = os.path.join(output_assets, 'style.css')
    if not os.path.exists(style_css_dest):
        defaults_style = os.path.join(defaults_dir, 'style.css')
        if os.path.exists(defaults_style):
            shutil.copy2(defaults_style, style_css_dest)

    # Always copy search.js from defaults
    defaults_search = os.path.join(defaults_dir, 'search.js')
    if os.path.exists(defaults_search):
        shutil.copy2(defaults_search, os.path.join(output_assets, 'search.js'))


def _get_template_path(template_name: str, templates_dir: str, defaults_templates_dir: str) -> str:
    """Find the template file path.

    Looks for:
    1. {templates_dir}/{template_name}.dtmpl
    2. {templates_dir}/default_{template_name}.dtmpl (for default templates)
    3. {defaults_templates_dir}/{template_name}.dtmpl
    4. {defaults_templates_dir}/default_{template_name}.dtmpl

    Args:
        template_name: Template name (without extension).
        templates_dir: User templates directory.
        defaults_templates_dir: Default templates directory.

    Returns:
        Path to the template file.

    Raises:
        BuildError: If template not found.
    """
    # Try user templates first (e.g., main_page.dtmpl or mainpage.dtmpl)
    for name in [template_name, f"default_{template_name}"]:
        path = os.path.join(templates_dir, f"{name}.dtmpl")
        if os.path.exists(path):
            return path

    # Try default templates
    for name in [template_name, f"default_{template_name}"]:
        path = os.path.join(defaults_templates_dir, f"{name}.dtmpl")
        if os.path.exists(path):
            return path

    raise BuildError(f"Template '{template_name}' not found")


def _build_mainpage(
    mainpage_template: str,
    project_name: str,
    version: str,
    templates_dir: str,
    defaults_templates_dir: str,
    build_root: str,
    tree: list[Node],
    search_index: str,
) -> None:
    """Build the main page (index.html) at build root level.

    Args:
        mainpage_template: Template name (without .dtmpl extension).
        project_name: Project name for page content.
        version: Version string for page content.
        templates_dir: User templates directory.
        defaults_templates_dir: Default templates directory.
        build_root: Root of build output (e.g., build/ from build/docs/).
        tree: Navigation tree.
        search_index: JSON search index string.
    """
    # Create a virtual node for the main page
    mainpage_node = Node(
        title=project_name,
        template=mainpage_template,
        params={
            'PROJECT_NAME': project_name,
            'VERSION': version,
        },
        output_path='index.html',
    )

    # Load template
    template_path = _get_template_path(mainpage_template, templates_dir, defaults_templates_dir)

    with open(template_path, 'r', encoding='utf-8') as f:
        template_content = f.read()

    # Render template (no source data for main page)
    rendered = render_template(template_content, mainpage_node.params, None, '', mainpage_node.output_path)

    # Convert markdown to HTML
    html_content = markdown_to_html(rendered)

    # Resolve cross-links (empty index for main page since it's at root)
    empty_index = CrossLinkIndex()
    html_content = resolve_links(html_content, empty_index, mainpage_node.output_path)

    # Assemble page
    page_html = assemble_page(html_content, mainpage_node, tree, project_name, version, search_index)

    # Write output to build_root/index.html
    output_path = os.path.join(build_root, 'index.html')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(page_html)


def build_docs(config_path: str) -> None:
    """Build all documentation.

    Args:
        config_path: Path to .sdoc.tree.

    Raises:
        BuildError: If the build fails.
    """
    try:
        # Step 1: Parse config and build tree
        tree, source_data_by_folder = build_tree(config_path)

        # Get config info for templates
        config_dir = os.path.dirname(os.path.abspath(config_path))
        from slop_doc.tree_builder import parse_main_config
        config = parse_main_config(config_path)

        project_name = config.get('project_name', 'Documentation')
        version = config.get('version', '')
        output_dir = os.path.join(config_dir, config.get('output_dir', 'build/docs/'))
        templates_dir = os.path.join(config_dir, config.get('templates_dir', 'docs/templates/'))
        assets_dir = os.path.join(config_dir, config.get('assets_dir', 'docs/assets/'))
        mainpage_template = config.get('mainpage', 'main_page')

        # Get defaults directory from package
        defaults_pkg = importlib.resources.files("slop_doc.defaults")
        defaults_dir = str(defaults_pkg)  # pathlib path to defaults folder
        defaults_templates_dir = os.path.join(defaults_dir, 'templates')
        defaults_style_css = os.path.join(defaults_dir, 'style.css')

        # Build root is the parent of output_dir (e.g., build/ from build/docs/)
        # Need to normalize to handle trailing slashes properly
        build_root = os.path.dirname(output_dir)

        # Step 2: Build cross-link index
        index = build_index(tree, source_data_by_folder)

        # Step 3: Generate search index (needed before page assembly)
        search_index = generate_search_index(tree, source_data_by_folder)

        # Step 3b: Build main page (index.html at build root)
        _build_mainpage(
            mainpage_template, project_name, version,
            templates_dir, defaults_templates_dir,
            build_root, tree, search_index
        )

        # Step 4: Process each node
        pages_built = 0
        for node in _iterate_nodes(tree):
            # Skip container nodes without a template
            if not node.template:
                continue

            try:
                # Load template (user dir first, then fall back to defaults)
                template_name = f"{node.template}.dtmpl"
                template_path = os.path.join(templates_dir, template_name)
                if not os.path.exists(template_path):
                    template_path = os.path.join(defaults_templates_dir, template_name)
                if not os.path.exists(template_path):
                    raise BuildError(f"Node '{node.title}': template '{node.template}' not found")

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
                page_html = assemble_page(html_content, node, tree, project_name, version, search_index)

                # Write output
                output_path = os.path.join(output_dir, node.output_path)
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(page_html)

                pages_built += 1

            except (TemplateEngineError, CrossLinkError) as e:
                raise BuildError(f"Node '{node.title}': {e}")

        # Step 5: Copy assets (user dir first, then fall back to defaults for style.css)
        _copy_assets_with_defaults(assets_dir, output_dir, defaults_dir)

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


def _find_config(directory: str | None = None) -> str:
    """Resolve config path.

    If directory is given, look for .sdoc.tree inside it.
    Otherwise look for .sdoc.tree in CWD.

    Raises:
        BuildError: If config not found.
    """
    if directory:
        path = os.path.abspath(os.path.join(directory, '.sdoc.tree'))
        if not os.path.isfile(path):
            raise BuildError(f"Config not found: {directory}/.sdoc.tree")
        return path

    path = os.path.join(os.getcwd(), '.sdoc.tree')
    if not os.path.isfile(path):
        raise BuildError(
            "No .sdoc.tree found in current directory.\n"
            "  Run 'slop-doc init' to create a docs folder, or pass -d <dir>."
        )
    return path


def _cmd_init(name: str) -> int:
    """Create a new docs folder with a default config."""
    import shutil

    target = os.path.join(os.getcwd(), name)
    if os.path.exists(target):
        print(f"Error: '{name}' already exists.", file=sys.stderr)
        return 1

    os.makedirs(target)

    # Copy default .sdoc.tree into the new folder
    defaults_pkg = importlib.resources.files("slop_doc.defaults")
    default_config = defaults_pkg / ".sdoc.tree"
    dest = os.path.join(target, ".sdoc.tree")

    with importlib.resources.as_file(default_config) as src:
        shutil.copy2(str(src), dest)

    print(f"Created '{name}/' with default config.")
    print(f"Edit '{name}/.sdoc.tree', then run 'slop-doc build' from '{name}/'.")
    return 0


def _cmd_open(config_path: str) -> int:
    """Open index.html from the build output directory."""
    import webbrowser
    from slop_doc.tree_builder import parse_main_config

    config = parse_main_config(config_path)
    config_dir = os.path.dirname(os.path.abspath(config_path))
    output_dir = os.path.join(config_dir, config.get('output_dir', 'build/docs/'))
    build_root = os.path.dirname(output_dir)
    index_html = os.path.join(build_root, 'index.html')

    if not os.path.isfile(index_html):
        print(f"Error: '{index_html}' not found. Run 'slop-doc build' first.", file=sys.stderr)
        return 1

    url = 'file:///' + index_html.replace('\\', '/')
    print(f"Opening {index_html}")
    webbrowser.open(url)
    return 0


def main() -> int:
    """Main CLI entry point.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    parser = argparse.ArgumentParser(
        prog='slop-doc',
        description='slop-doc - Static documentation generator',
    )
    subparsers = parser.add_subparsers(dest='command', metavar='command')
    subparsers.required = True

    # init
    p_init = subparsers.add_parser('init', help='Create a new docs folder with default config')
    p_init.add_argument('--name', default='docs', help='Docs folder name (default: docs)')

    # build
    p_build = subparsers.add_parser('build', help='Build documentation')
    p_build.add_argument('-d', '--dir', default=None, metavar='DIR', help='Docs folder containing .sdoc.tree')

    # open
    p_open = subparsers.add_parser('open', help='Open built documentation in browser')
    p_open.add_argument('-d', '--dir', default=None, metavar='DIR', help='Docs folder containing .sdoc.tree')

    args = parser.parse_args()

    try:
        if args.command == 'init':
            return _cmd_init(args.name)

        if args.command == 'build':
            config_path = _find_config(args.dir)
            build_docs(config_path)
            return 0

        if args.command == 'open':
            config_path = _find_config(args.dir)
            return _cmd_open(config_path)

    except BuildError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1

    return 0
