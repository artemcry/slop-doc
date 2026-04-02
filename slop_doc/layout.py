"""Stage 7: Layout Generator & HTML Output - generates the 3-column layout."""

from __future__ import annotations

import json
import os
import posixpath
from dataclasses import dataclass

from slop_doc.tree_builder import Node


def _assets_prefix(output_path: str) -> str:
    """Return the relative prefix needed to reach the output root from output_path."""
    depth = output_path.count('/')
    return '../' * depth


def _relative_url(from_path: str, to_path: str) -> str:
    """Compute a relative URL from from_path to to_path (both relative to output root)."""
    from_dir = posixpath.dirname(from_path)
    rel = posixpath.relpath(to_path, from_dir) if from_dir else to_path
    return rel.replace('\\', '/')


class LayoutError(Exception):
    """Raised when layout generation fails."""
    pass


@dataclass
class BreadcrumbItem:
    """Represents a breadcrumb item."""
    title: str
    url: str


def generate_nav_tree(tree: list[Node], current: Node | None = None, expand_parents: bool = True) -> str:
    """Generate navigation tree HTML.

    Args:
        tree: The navigation tree.
        current: The current node (to highlight).
        expand_parents: Whether to expand parent nodes of current.

    Returns:
        HTML string for the navigation tree.
    """
    current_path = current.output_path if current else None
    html = '<ul class="nav-tree">\n'
    for node in tree:
        html += _generate_nav_node(node, current_path, current_path, expand_parents)
    html += '</ul>\n'
    return html


def _generate_nav_node(node: Node, current_path: str | None, page_path: str | None, expand_parents: bool) -> str:
    """Generate a single nav node and its children.

    Args:
        node: The node to render.
        current_path: output_path of the currently displayed page (for highlight).
        page_path: output_path of the page being assembled (for computing relative hrefs).
        expand_parents: Whether to expand parent nodes of current.

    Returns:
        HTML string for the node.
    """
    is_current = current_path is not None and node.output_path == current_path
    has_children = len(node.children) > 0
    is_container = not node.template  # No template = container/group node

    if current_path is None:
        should_expand = True
    else:
        should_expand = expand_parents and _is_ancestor(node, current_path)

    classes = ['nav-item']
    if is_current:
        classes.append('active')
    if is_container:
        classes.append('nav-group')

    children_expanded = should_expand or is_current or is_container if has_children else False
    if has_children:
        classes.append('has-children')
        classes.append('expanded' if children_expanded else 'collapsed')

    classes_str = ' '.join(classes)
    html = f'<li class="{classes_str}">\n'

    if is_container or not node.output_path:
        # Container node — not a clickable link
        html += f'<span class="nav-label">{node.title}</span>\n'
    else:
        href = _relative_url(page_path, node.output_path) if page_path else node.output_path
        extra = ' class="active"' if is_current else ''
        html += f'<a href="{href}"{extra}>{node.title}</a>\n'

    if has_children:
        # Always render children but control visibility via CSS class
        ul_class = 'expanded' if children_expanded else 'collapsed'
        html += f'<ul class="nav-children {ul_class}">\n'
        for child in node.children:
            html += _generate_nav_node(child, current_path, page_path, expand_parents)
        html += '</ul>\n'
        # Toggle arrow button (aligned right)
        html += '<span class="nav-toggle" aria-hidden="true"></span>\n'

    html += '</li>\n'
    return html


def _is_ancestor(ancestor: Node, descendant_path: str) -> bool:
    """Check if ancestor contains a node with descendant_path anywhere in its subtree."""
    for child in ancestor.children:
        if child.output_path == descendant_path:
            return True
        if _is_ancestor(child, descendant_path):
            return True
    return False


def generate_breadcrumb(node: Node, tree: list[Node]) -> list[BreadcrumbItem]:
    """Generate breadcrumb items for a node.

    Args:
        node: The current node.
        tree: The full navigation tree.

    Returns:
        List of BreadcrumbItems from root to current.
    """
    breadcrumb: list[BreadcrumbItem] = []

    # Find the path to this node
    path = _find_node_path(tree, node)

    for n in path:
        breadcrumb.append(BreadcrumbItem(title=n.title, url=n.output_path))

    return breadcrumb


def _find_node_path(tree: list[Node], target: Node, path: list[Node] | None = None) -> list[Node]:
    """Find the path from root to target node.

    Args:
        tree: The navigation tree.
        target: The target node.
        path: Current path (for recursion).

    Returns:
        List of nodes from root to target.
    """
    if path is None:
        path = []

    for node in tree:
        current_path = path + [node]
        if node.output_path == target.output_path:
            return current_path
        if node.children:
            result = _find_node_path(node.children, target, current_path)
            if result:
                return result

    return []


def generate_contents_sidebar(html_content: str) -> str:
    """Extract h2/h3 headings from HTML and generate contents sidebar.

    Args:
        html_content: The rendered HTML content.

    Returns:
        HTML string for the contents sidebar.
    """
    import re

    # Find all h2 and h3 with their ids - capture inner text properly
    pattern = r'<h([23])[^>]*id="([^"]+)"[^>]*>(.*?)</h[23]>'
    matches = re.findall(pattern, html_content, re.DOTALL)

    if not matches:
        return ""

    html = '<div class="contents-sidebar">\n'
    html += '<h4>Contents</h4>\n'
    html += '<ul>\n'

    for level, anchor_id, inner in matches:
        # Strip all HTML tags to get plain text
        text = re.sub(r'<[^>]+>', '', inner).strip()
        level_class = 'h2' if level == '2' else 'h3'
        html += f'<li class="{level_class}"><a href="#{anchor_id}">{text}</a></li>\n'

    html += '</ul>\n'
    html += '</div>\n'

    return html


def generate_search_index(tree: list[Node], source_data_by_folder: dict[str, any]) -> str:
    """Generate search index JSON.

    Args:
        tree: The navigation tree.
        source_data_by_folder: Dict of source data by folder.

    Returns:
        JSON string for the search index.
    """
    index = []
    processed_sources = set()

    # Build a mapping from class name -> detail page URL
    # by scanning all nodes and looking for class detail pages
    class_page_urls = {}
    folder_page_urls = {}

    def scan_for_class_pages(node: Node):
        # If a node has a title like "Pipeline Class" and output_path like
        # "api-reference/dataflow/pipeline-class.html", extract "Pipeline"
        if node.title and node.output_path:
            # Check if this looks like a class detail page
            if '-class.html' in node.output_path:
                class_name = node.title.replace(' Class', '')
                class_page_urls[class_name] = node.output_path
        for child in node.children:
            scan_for_class_pages(child)

    for node in tree:
        scan_for_class_pages(node)

    def process_node(node: Node):
        entry = {
            'title': node.title,
            'url': node.output_path,
            'type': 'page'
        }
        index.append(entry)

        # Add class and function names from source data (only once per source)
        if node.source and node.source not in processed_sources:
            processed_sources.add(node.source)
            if node.source in source_data_by_folder:
                source_data = source_data_by_folder[node.source]

                # Add classes with their detail page URL if found, else folder URL
                for cls in source_data.classes:
                    class_url = class_page_urls.get(cls.name, node.output_path)
                    index.append({
                        'title': cls.name,
                        'url': class_url,
                        'type': 'class'
                    })
                    # Add all methods (public, private, dunder) for search
                    for method in cls.methods:
                        index.append({
                            'title': f"{cls.name}.{method.name}",
                            'url': f"{class_url}#{method.name}",
                            'type': 'method'
                        })

                # Add module-level functions
                for func in source_data.functions:
                    index.append({
                        'title': func.name,
                        'url': node.output_path,
                        'type': 'function'
                    })

                # Add constants
                for const in source_data.constants:
                    index.append({
                        'title': const.name,
                        'url': node.output_path,
                        'type': 'constant'
                    })

        for child in node.children:
            process_node(child)

    for node in tree:
        process_node(node)

    return json.dumps(index, indent=2)


def assemble_page(
    content: str,
    node: Node,
    tree: list[Node],
    project_name: str,
    version: str,
    search_index: str = ''
) -> str:
    """Assemble a complete HTML page with 3-column layout.

    Args:
        content: The rendered page content (center column).
        node: The current node.
        tree: The navigation tree.
        project_name: Project name for header.
        version: Version string.
        search_index: JSON string for search index (embedded inline).

    Returns:
        Complete HTML page.
    """
    prefix = _assets_prefix(node.output_path)

    # Generate navigation (with relative hrefs from this page)
    nav_html = generate_nav_tree(tree, node)
    # Rebuild nav with relative hrefs specific to this page's location
    current_path = node.output_path
    nav_html = '<ul class="nav-tree">\n'
    for n in tree:
        nav_html += _generate_nav_node(n, current_path, current_path, True)
    nav_html += '</ul>\n'

    # Generate breadcrumb
    breadcrumb_items = generate_breadcrumb(node, tree)
    breadcrumb_html = _render_breadcrumb(breadcrumb_items, project_name, node.output_path)

    # Generate contents sidebar
    contents_html = generate_contents_sidebar(content)

    # Assemble full page
    html = f'''<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{node.title} — {project_name}</title>
  <link rel="stylesheet" href="{prefix}assets/style.css">
</head>
<body>
  <header>
    <span class="project-name">{project_name}</span>
    <div class="breadcrumb">{breadcrumb_html}</div>
    <div class="search">
      <input type="text" placeholder="Search..." id="search-input">
    </div>
  </header>
  <div class="layout">
    <nav class="sidebar-left">
      {nav_html}
    </nav>
    <main class="content">
      {content}
    </main>
    <aside class="sidebar-right">
      {contents_html}
    </aside>
  </div>
  <script src="{prefix}assets/search.js"></script>
  <script>
  // Embedded search index (avoids XHR CORS issues with file:// protocol)
  window.__SEARCH_INDEX__ = {search_index};
  // Prefix for search result URLs (computed server-side by layout.py)
  window.__SEARCH_PREFIX__ = '{prefix}';
  </script>
  <script>
(function() {{
  // Scroll spy - highlight current section in contents sidebar
  var tocLinks = document.querySelectorAll('.contents-sidebar a');
  var headings = [];

  // Collect all heading IDs
  document.querySelectorAll('h2[id], h3[id], .method-detail[id]').forEach(function(el) {{
    headings.push({{ id: el.id, el: el }});
  }});

  function highlightCurrent() {{
    var scrollY = window.scrollY + 60;
    var current = null;

    for (var i = headings.length - 1; i >= 0; i--) {{
      var h = headings[i].el;
      if (h.offsetTop <= scrollY) {{
        current = headings[i].id;
        break;
      }}
    }}

    tocLinks.forEach(function(link) {{
      link.classList.remove('current');
      if (current && link.getAttribute('href') === '#' + current) {{
        link.classList.add('current');
        link.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
      }}
    }});
  }}

  window.addEventListener('scroll', highlightCurrent);
  highlightCurrent();
}})();
  </script>
</body>
</html>'''

    return html


def _render_breadcrumb(items: list[BreadcrumbItem], project_name: str, page_path: str = '') -> str:
    """Render breadcrumb HTML.

    Args:
        items: Breadcrumb items.
        project_name: Project name.
        page_path: Current page's output path (for relative URLs).

    Returns:
        HTML string for breadcrumb.
    """
    prefix = _assets_prefix(page_path)
    root_href = f'{prefix}index.html' if prefix else 'index.html'
    html = f'<a href="{root_href}">{project_name}</a>'
    for item in items:
        href = _relative_url(page_path, item.url) if page_path else item.url
        html += f' &gt; <a href="{href}">{item.title}</a>'
    return html


def copy_assets(assets_dir: str, output_dir: str) -> None:
    """Copy assets directory to output.

    Args:
        assets_dir: Source assets directory.
        output_dir: Destination directory.
    """
    import shutil

    if not os.path.exists(assets_dir):
        return

    output_assets = os.path.join(output_dir, 'assets')
    if os.path.exists(output_assets):
        shutil.rmtree(output_assets)
    shutil.copytree(assets_dir, output_assets)
