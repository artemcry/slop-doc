"""Build Orchestrator — drives the full documentation build.

New pipeline:
    1. Walk docs folder → Node tree + SourceData cache
    2. Build cross-link index
    3. Generate search index
    4. For each node:
       a. Render tags ({{data}} + %presentation()%) in Markdown body
       b. Convert Markdown → HTML
       c. Resolve [[cross-links]]
       d. Assemble 3-column HTML page
       e. Write to output_dir
    5. Copy assets
"""

from __future__ import annotations

import argparse
import importlib.resources
import json
import os
import re
import shutil
import sys

from slop_doc.tree_builder import (
    build_tree, build_tree_with_root, Node, TreeBuilderError,
)
from slop_doc.tag_renderer import (
    render_data_tags_inline,
    render_presentation_functions,
    render_function_detail,
    link_type_if_class,
    TagRendererError,
)
from slop_doc.parser import SourceData
from slop_doc.cross_links import build_index, resolve_links, CrossLinkError, CrossLinkIndex
from slop_doc.markdown_renderer import markdown_to_html
from slop_doc.layout import assemble_page, generate_search_index


class BuildError(Exception):
    """Raised when the build fails."""
    pass


# ---------------------------------------------------------------------------
# Project config  (read from root.md front-matter)
# ---------------------------------------------------------------------------

def _read_project_config(docs_root: str) -> dict:
    """Read project-level config from root.md front-matter.

    Recognised keys in front-matter ``raw``:
        project_name, version, output_dir, assets_dir
    """
    from slop_doc.frontmatter import parse_frontmatter, FrontmatterError

    root_md = os.path.join(docs_root, 'root.md')
    if not os.path.isfile(root_md):
        return {}

    with open(root_md, 'r', encoding='utf-8') as f:
        raw = f.read()

    try:
        meta, _ = parse_frontmatter(raw)
    except FrontmatterError:
        return {}

    return meta.raw


# ---------------------------------------------------------------------------
# Asset copying
# ---------------------------------------------------------------------------

def _copy_assets(assets_dir: str | None, output_dir: str, defaults_dir: str) -> None:
    """Copy assets into output_dir/assets/.

    User assets_dir takes priority; missing style.css falls back to defaults.
    app.js always comes from defaults.
    """
    output_assets = os.path.join(output_dir, 'assets')
    if os.path.exists(output_assets):
        shutil.rmtree(output_assets)
    os.makedirs(output_assets, exist_ok=True)

    # Copy user assets
    if assets_dir and os.path.isdir(assets_dir):
        for item in os.listdir(assets_dir):
            src = os.path.join(assets_dir, item)
            dst = os.path.join(output_assets, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

    # Fallback style.css
    style_dest = os.path.join(output_assets, 'style.css')
    if not os.path.exists(style_dest):
        default_style = os.path.join(defaults_dir, 'style.css')
        if os.path.exists(default_style):
            shutil.copy2(default_style, style_dest)

    # Always copy app.js from defaults
    default_app = os.path.join(defaults_dir, 'app.js')
    if os.path.exists(default_app):
        shutil.copy2(default_app, os.path.join(output_assets, 'app.js'))


# ---------------------------------------------------------------------------
# Auto-generated page content  (for class / function child nodes)
# ---------------------------------------------------------------------------

def _generate_auto_class_content(class_name: str) -> str:
    """Generate Markdown body for an auto-generated class page."""
    return f"""# {class_name}

%class_description({class_name})%

## Info

%class_info({class_name})%

%properties({class_name})%

%methods_table({class_name})%

%methods_table({class_name}, private)%

%methods_details({class_name})%
"""


def _generate_auto_file_functions_content(
    module_name: str,
    source_data: SourceData,
    folder_slug: str,
) -> str:
    """Generate HTML content for a file-functions page (all functions from one .py file)."""
    funcs = [f for f in source_data.functions if
             os.path.splitext(os.path.basename(f.source_file))[0] == module_name]
    if not funcs:
        return f"<h1>Module: {module_name}</h1>\n<p>No functions found.</p>"

    parts = [f"<h1>Module: {module_name}</h1>\n"]

    # Summary table (name is a link, types are cross-linked)
    rows = []
    for func in funcs:
        sig_parts = []
        for arg in func.args:
            s = arg.name
            if arg.type:
                s += f": {link_type_if_class(arg.type, source_data, folder_slug)}"
            if arg.default:
                s += f"={arg.default}"
            sig_parts.append(s)
        params_str = ', '.join(sig_parts)
        ret_str = f" -&gt; {link_type_if_class(func.return_type, source_data, folder_slug)}" if func.return_type else ""
        desc = func.short_description or "No description"
        rows.append(
            f'<tr><td><a href="#{func.name}">{func.name}</a>'
            f'<code>({params_str}){ret_str}</code></td><td>{desc}</td></tr>'
        )

    parts.append(
        "<table class='functions-table'>\n"
        "<thead><tr><th>Function</th><th>Description</th></tr></thead>\n"
        f"<tbody>\n{''.join(rows)}\n</tbody>\n</table>\n"
    )

    # Detail blocks
    parts.append("<h2>Function Details</h2>\n")
    for func in funcs:
        parts.append(render_function_detail(func, source_data, folder_slug))

    return '\n'.join(parts)



# ---------------------------------------------------------------------------
# Build pipeline
# ---------------------------------------------------------------------------

def build_docs(docs_root: str) -> None:
    """Build all documentation from a docs folder.

    Args:
        docs_root: Path to the documentation root (folder containing root.md).

    Raises:
        BuildError: If the build fails.
    """
    try:
        # --- Config ---
        config = _read_project_config(docs_root)
        project_name = config.get('project_name', 'Documentation')
        version = config.get('version', '')
        output_dir = os.path.join(docs_root, config.get('output_dir', 'build'))
        assets_dir_raw = config.get('assets_dir')
        assets_dir = os.path.join(docs_root, assets_dir_raw) if assets_dir_raw else None

        # --- Settings (all optional, safe defaults) ---
        settings = {
            'editor': config.get('editor', ''),
            'max_search_results': int(config.get('max_search_results', 12)),
            'default_collapsed': bool(config.get('default_collapsed', False)),
        }
        exclude_dirs_extra = config.get('exclude_dirs', [])

        defaults_pkg = importlib.resources.files("slop_doc.defaults")
        defaults_dir = str(defaults_pkg)

        os.makedirs(output_dir, exist_ok=True)

        # --- Step 1: Build tree ---
        output_dir_name = os.path.basename(output_dir.rstrip('/\\'))
        exclude = {output_dir_name} | set(exclude_dirs_extra)
        root_node, source_data_by_folder = build_tree_with_root(docs_root, exclude_dirs=exclude)
        tree = root_node.children  # top-level nav tree

        # --- Step 2: Build cross-link index ---
        index = build_index(tree, source_data_by_folder)

        # --- Step 3: Search index ---
        search_index = generate_search_index(tree, source_data_by_folder)

        # --- Step 4: Build index.html from root.md content ---
        if root_node.content:
            _build_page(
                root_node, root_node.content, tree, index,
                project_name, version, search_index, output_dir,
                source_data_by_folder, is_index=True, docs_root=docs_root,
                settings=settings,
            )

        # --- Step 5: Build all pages ---
        pages_built = 0
        all_nodes = _iterate_nodes(tree)
        generated_file_pages: set[str] = set()

        for node in all_nodes:
            body = node.content
            raw_html = False

            # Function-link nav node → generate the file-function page it points to (once)
            if node.is_auto and node.auto_function:
                file_output_path = node.output_path.split('#')[0]
                if file_output_path not in generated_file_pages:
                    generated_file_pages.add(file_output_path)
                    source_data = source_data_by_folder.get(node.source)
                    if source_data and node.auto_source_file:
                        folder_slug = os.path.basename(node.source.rstrip('/\\'))
                        body = _generate_auto_file_functions_content(
                            node.auto_source_file, source_data, folder_slug
                        )
                        file_page_node = Node(
                            title=node.auto_source_file,
                            source=node.source,
                            output_path=file_output_path,
                            is_auto=True,
                            auto_source_file=node.auto_source_file,
                        )
                        _build_page(
                            file_page_node, body, tree, index,
                            project_name, version, search_index, output_dir,
                            source_data_by_folder, is_raw_html=True, docs_root=docs_root,
                            settings=settings,
                        )
                        pages_built += 1
                continue

            # Auto-generated class page
            if node.is_auto and node.auto_class:
                body = _generate_auto_class_content(node.auto_class)
            # Auto file-function page (if created directly in tree)
            elif node.is_auto and node.auto_source_file:
                source_data = source_data_by_folder.get(node.source)
                if source_data:
                    folder_slug = os.path.basename(node.source.rstrip('/\\')) if node.source else ''
                    body = _generate_auto_file_functions_content(
                        node.auto_source_file, source_data, folder_slug
                    )
                    raw_html = True
                else:
                    body = f"# {node.auto_source_file}\n\n*No source data.*\n"

            if not body and not node.children:
                continue  # skip empty container nodes without content

            if not node.output_path:
                continue  # container node (no root.md) — no page to generate

            if not body:
                # Folder node with children but no content — generate a simple listing
                body = f"# {node.title}\n"

            _build_page(
                node, body, tree, index,
                project_name, version, search_index, output_dir,
                source_data_by_folder,
                is_raw_html=raw_html, docs_root=docs_root,
                settings=settings,
            )
            pages_built += 1

        # --- Step 6: Copy assets ---
        _copy_assets(assets_dir, output_dir, defaults_dir)

        print(f"Built {pages_built} pages to {output_dir}")

    except TreeBuilderError as e:
        raise BuildError(f"Tree error: {e}")


_PDF_EMBED_RE = re.compile(r'data-pdf-src="([^"]+)"')


def _build_page(
    node: Node,
    body: str,
    tree: list[Node],
    index: CrossLinkIndex,
    project_name: str,
    version: str,
    search_index: str,
    output_dir: str,
    source_data_by_folder: dict,
    is_index: bool = False,
    is_raw_html: bool = False,
    docs_root: str = "",
    settings: dict | None = None,
) -> None:
    """Render and write a single page."""
    # Get source data for this node
    source_data = None
    if node.source and node.source in source_data_by_folder:
        source_data = source_data_by_folder[node.source]

    # Compute folder_slug for cross-links
    folder_slug = ""
    if node.source:
        folder_slug = os.path.basename(node.source.rstrip('/\\'))

    try:
        if is_raw_html:
            # Body is already HTML (e.g. file-function pages) — skip tag/Markdown processing
            html_content = body
        else:
            # Render %presentation()% functions first (they expand {{tags}} in their own args)
            rendered = render_presentation_functions(body, source_data, folder_slug, node.output_path)

            # Render remaining {{data}} tags inline (bare tags not inside %...%)
            rendered = render_data_tags_inline(rendered, source_data, folder_slug)

            # Markdown → HTML
            html_content = markdown_to_html(rendered)

        # Resolve [[cross-links]]
        html_content = resolve_links(html_content, index, node.output_path)

        # Assemble 3-column page
        page_html = assemble_page(html_content, node, tree, project_name, version, search_index, settings=settings)

        # Write
        if is_index:
            out_path = os.path.join(output_dir, 'index.html')
        else:
            out_path = os.path.join(output_dir, node.output_path)

        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(page_html)

        # Copy inline %pdf()% files to output directory next to the HTML page
        if docs_root:
            path_base = os.path.dirname(os.path.abspath(docs_root))
            page_out_dir = os.path.dirname(out_path)
            for pdf_match in _PDF_EMBED_RE.finditer(html_content):
                pdf_rel = pdf_match.group(1)
                pdf_src = os.path.join(path_base, pdf_rel)
                if os.path.isfile(pdf_src):
                    shutil.copy2(pdf_src, os.path.join(page_out_dir, os.path.basename(pdf_rel)))

    except (TagRendererError, CrossLinkError) as e:
        raise BuildError(f"Page '{node.title}': {e}")


def _iterate_nodes(tree: list[Node]) -> list[Node]:
    """Flatten the tree into a list of all nodes."""
    nodes = []
    for node in tree:
        nodes.append(node)
        if node.children:
            nodes.extend(_iterate_nodes(node.children))
    return nodes


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def _find_docs_root(directory: str | None = None) -> str:
    """Resolve docs root: a folder containing root.md."""
    if directory:
        path = os.path.abspath(directory)
        if os.path.isfile(os.path.join(path, 'root.md')):
            return path
        raise BuildError(f"No root.md found in {directory}")

    cwd = os.getcwd()
    if os.path.isfile(os.path.join(cwd, 'root.md')):
        return cwd

    raise BuildError(
        "No root.md found in current directory.\n"
        "  Run 'slop-doc init' to create a docs folder, or pass -d <dir>."
    )


def _cmd_init(name: str) -> int:
    """Scaffold a new docs folder with a root.md."""
    target = os.path.join(os.getcwd(), name)
    if os.path.exists(target):
        print(f"Error: '{name}' already exists.", file=sys.stderr)
        return 1

    os.makedirs(target)

    root_md = os.path.join(target, 'root.md')
    with open(root_md, 'w', encoding='utf-8') as f:
        f.write('{\n'
                '    "title": "My Project",\n'
                '    "project_name": "My Project",\n'
                '    "version": "1.0.0",\n'
                '    "output_dir": "build",\n'
                '    "editor": ""\n'
                '}\n\n'
                '# Welcome\n\n'
                'Edit this file and add .md pages to build your documentation.\n')

    print(f"Created '{name}/' with root.md.")
    print(f"Add .md files, then run 'slop-doc build -d {name}/'.")
    return 0


_LIVERELOAD_SCRIPT = b"""<script>
(function(){
  var es=new EventSource('/__livereload');
  es.onmessage=function(e){if(e.data==='reload')location.reload();};
  es.onerror=function(){es.close();setTimeout(function(){
    es=new EventSource('/__livereload');},2000);};
})();
</script>"""


def _cmd_start(docs_root: str, port: int = 8000, open_browser: bool = False) -> int:
    """Build, serve, watch for changes and live-reload the browser."""
    import threading
    import webbrowser
    from http.server import HTTPServer, SimpleHTTPRequestHandler
    from socketserver import ThreadingMixIn

    from slop_doc.watcher import DocsWatcher

    config = _read_project_config(docs_root)
    output_dir = os.path.join(docs_root, config.get('output_dir', 'build'))
    if port == 8000:
        port = int(config.get('port', 8000))

    # --- initial build ---
    print("Building docs...")
    build_docs(docs_root)

    # --- SSE state (shared between handler instances) ---
    sse_clients: list[threading.Event] = []
    sse_lock = threading.Lock()

    def _notify_clients():
        with sse_lock:
            for ev in sse_clients:
                ev.set()

    def _rebuild():
        print("  Rebuilding...")
        build_docs(docs_root)
        print("  Done.")

    # --- HTTP handler with livereload injection ---
    class _LiveHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=output_dir, **kwargs)

        def log_message(self, format, *args):
            pass

        def _handle_sse(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            ev = threading.Event()
            with sse_lock:
                sse_clients.append(ev)
            try:
                while True:
                    ev.wait()
                    ev.clear()
                    self.wfile.write(b'data: reload\n\n')
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                with sse_lock:
                    if ev in sse_clients:
                        sse_clients.remove(ev)

        def do_GET(self):
            if self.path == '/__livereload':
                return self._handle_sse()

            # Resolve the file path
            path = self.translate_path(self.path)
            if os.path.isdir(path):
                index = os.path.join(path, 'index.html')
                if os.path.isfile(index):
                    path = index
                else:
                    return super().do_GET()

            if path.endswith('.html') and os.path.isfile(path):
                with open(path, 'rb') as f:
                    data = f.read()
                if b'</body>' in data:
                    data = data.replace(b'</body>', _LIVERELOAD_SCRIPT + b'\n</body>', 1)
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            super().do_GET()

    class _ThreadedServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    # --- start watcher ---
    watcher = DocsWatcher(docs_root, output_dir,
                          rebuild_fn=_rebuild,
                          on_rebuild=_notify_clients)
    watcher.start()

    # --- find free port & start server ---
    for p in range(port, port + 100):
        try:
            server = _ThreadedServer(('127.0.0.1', p), _LiveHandler)
            break
        except OSError:
            continue
    else:
        watcher.stop()
        print("Error: could not find a free port.", file=sys.stderr)
        return 1

    url = f'http://127.0.0.1:{p}'
    print(f"Serving at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        server.server_close()
    return 0


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='slop-doc',
        description='slop-doc — Static documentation generator',
    )
    subparsers = parser.add_subparsers(dest='command', metavar='command')
    subparsers.required = True

    # init
    p_init = subparsers.add_parser('init', help='Create a new docs folder with root.md')
    p_init.add_argument('--name', default='docs', help='Docs folder name (default: docs)')

    # build
    p_build = subparsers.add_parser('build', help='Build documentation')
    p_build.add_argument('-d', '--dir', default=None, metavar='DIR', help='Docs folder containing root.md')

    # start
    p_start = subparsers.add_parser('start', help='Build, serve with live reload, and watch for changes')
    p_start.add_argument('-d', '--dir', default=None, metavar='DIR', help='Docs folder containing root.md')
    p_start.add_argument('-p', '--port', default=8000, type=int, metavar='PORT', help='HTTP port (default: 8000)')
    p_start.add_argument('-o', '--open', action='store_true', help='Open browser automatically')

    args = parser.parse_args()

    try:
        if args.command == 'init':
            return _cmd_init(args.name)

        if args.command == 'build':
            docs_root = _find_docs_root(args.dir)
            build_docs(docs_root)
            return 0

        if args.command == 'start':
            docs_root = _find_docs_root(args.dir)
            return _cmd_start(docs_root, port=args.port, open_browser=args.open)

    except BuildError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1

    return 0
