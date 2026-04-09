# slop-doc

Static documentation generator for Python projects. Parses Python source code via AST, renders Markdown pages with embedded data tags and presentation functions into a styled 3-column HTML site with navigation tree, cross-linking, and search.

## Installation

```bash
pip install slop-doc
```

Requires Python >= 3.10. Dependencies: `markdown`, `watchdog`.

## Quick Start

```bash
# 1. Create a docs folder with starter root.md
slop-doc init --name docs

# 2. Edit docs/root.md, add .md pages

# 3. Build
slop-doc build -d docs

# 4. Serve with live reload (auto-rebuild + browser refresh on file changes)
slop-doc start -d docs

# 4b. Same but also open browser automatically
slop-doc start -d docs --open
```

## CLI Commands

| Command | Description |
|---|---|
| `slop-doc init [--name <folder>]` | Create a new docs folder with a starter `root.md` and `slop-doc-instruction.md` next to it. Default name: `docs` |
| `slop-doc build [-d <dir>]` | Build documentation. Looks for `root.md` in `-d` dir or current directory |
| `slop-doc start [-d <dir>] [-p <port>] [-o\|--open]` | Build, serve, and **live-reload** — watches for file changes, rebuilds automatically, and refreshes the browser via SSE. `--open` opens the browser. Default port from config or 8000 |

---

## How It Works

The folder structure **is** the documentation tree. Every `.md` file becomes a page; every subfolder with a `root.md` becomes a folder node in the navigation. Subfolders **without** `root.md` but containing `.md` files become **container nodes** — they appear in the nav tree and group their children, but don't open a page themselves.

```
my-docs/                    <- docs root (contains root.md)
+-- root.md                 <- project config + landing page
+-- getting-started.md
+-- installation.md
+-- usage.md
+-- api/                    <- subfolder with root.md + content = folder node
|   +-- root.md             <- folder config + folder landing page
|   +-- overview.md         <- page inside the folder
|   +-- advanced/
|       +-- root.md
+-- data/                   <- root.md with only {} = container with config
|   +-- root.md             <- frontmatter works (py_source, children), but no page
|   +-- overview.md
+-- guides/                 <- subfolder WITHOUT root.md = container node
    +-- tutorial.md         <- children appear under "Guides" in nav
    +-- faq.md
```

**Container nodes** come in two forms:
- **Folder without `root.md`**: title derived from folder name, no config possible
- **Folder with `root.md` but no body content** (e.g., just `{}`): same container behavior but frontmatter keys like `py_source`, `children`, `order` still work

Both types derive their title from the folder name (same rules as `.md` files — numeric prefixes stripped, separators cleaned, title-cased). Clicking a container node in the nav tree toggles its children — no page is generated.

**Build output**: a self-contained HTML site with `assets/style.css`, `assets/app.js`, and one `.html` per page. Use `slop-doc start` to serve locally with **live reload** — edit any `.md` file and the browser refreshes automatically. Pages load via SPA navigation (no full reload, smooth fade transitions). Also works with `file://` protocol (falls back to standard page loads).

---

## Front-matter

Each `.md` file can start with a JSON config block. The block is relaxed JSON — supports `//` comments, `#` comments, trailing commas, and unquoted keys.

```markdown
{
    "title": "My Page",
    "py_source": "../src/mypackage"
}

# My Page

Page content here...
```

### Page-level keys

| Key | Type | Description |
|---|---|---|
| `title` | `string` | Display name in the nav tree. Falls back to the first `#` heading, then filename |
| `py_source` | `string` | Path to Python source folder for this page (and its children). Resolved relative to the **parent directory** of the docs root |
| `children` | `object` | Auto-generated child pages from source code. See [Children](#children) |
| `order` | `int` | Explicit sort position in the nav tree (lower = shown first). Optional — unordered pages keep their filename-based position after ordered ones |

### Project-level keys (only in the root `root.md`)

| Key | Type | Default | Description |
|---|---|---|---|
| `project_name` | `string` | `"Documentation"` | Displayed in the site header |
| `version` | `string` | `""` | Shown in page titles |
| `output_dir` | `string` | `"build"` | Output folder (relative to docs root) |
| `assets_dir` | `string` | — | Custom assets folder (relative to docs root). Files here override defaults |
| `editor` | `string` | `""` | Editor URI scheme for double-click open (`"vscode"`, `"vscodium"`, `"cursor"`). Empty to disable |
| `exclude_dirs` | `list` | `[]` | Extra directory names to skip when scanning the docs folder |
| `max_search_results` | `int` | `12` | Maximum number of results in the search dropdown |
| `default_collapsed` | `bool` | `false` | If true, the nav tree starts fully collapsed on first visit |
| `port` | `int` | `8000` | Default port for `slop-doc start` (overridden by CLI `-p`) |

### Example root.md

```json
{
    "title": "MyProject Docs",
    "project_name": "MyProject",
    "version": "2.1.0",
    "output_dir": "build",
    "py_source": "../src/myproject",
    "editor": "vscode",
    "exclude_dirs": ["drafts", "archive"],
    "max_search_results": 8,
    "default_collapsed": false,
    "port": 9000
}

# Welcome to MyProject

This is the landing page.
```

---

## Source Folder

The `py_source` key tells slop-doc where to find your Python source code. It is **inherited** by child pages — set it once on a folder's `root.md` and all pages inside that folder use it automatically.

A deeper `root.md` or individual page can override it with its own `py_source`.

**Path resolution**: always relative to the **parent of the docs root**, not relative to the `.md` file. For example, if your docs are in `project/docs/` and your source is in `project/src/mypackage/`, use:

```json
{
    "py_source": "../src/mypackage"
}
```

This works regardless of how deeply nested the `.md` file is.

---

## Data Tags

Data tags are placeholders in Markdown that expand to lists of items from your Python source code. Write them as `{{tag_name}}` in the page body.

### Available tags

| Tag | What it lists |
|---|---|
| `{{classes}}` | All classes (from files directly in the source folder) |
| `{{functions}}` | All module-level functions |
| `{{constants}}` | All constants (ALL_CAPS names) |
| `{{enums}}` | Enum classes |
| `{{dataclasses}}` | Dataclass classes |
| `{{interfaces}}` | Abstract base classes (ABC / have abstract methods) |
| `{{protocols}}` | Protocol classes |
| `{{exceptions}}` | Exception classes |
| `{{plain_classes}}` | Regular classes that don't fit any category above |

Each tag has a **recursive variant** with `_rec` suffix that includes files from all subfolders:

| Flat (direct files only) | Recursive (all subfolders) |
|---|---|
| `{{classes}}` | `{{classes_rec}}` |
| `{{functions}}` | `{{functions_rec}}` |
| `{{enums}}` | `{{enums_rec}}` |
| ... | ... |

### Inline rendering

In the page body, class-type tags render as cross-linked lists:

```markdown
## Available Classes

{{classes}}
```

Becomes something like: `DataSource, FetchSpec, ColumnMap` — each name is a clickable cross-link to its class page.

If no items are found, renders as: *None found.*

---

## Children (Auto-Generated Pages)

The `children` key in front-matter generates child pages from source code. Each child gets a full dedicated page with class/function documentation.

```json
{
    "title": "API Reference",
    "py_source": "../src/mypackage",
    "children": {
        "classes": "{{classes}}"
    }
}
```

This creates a child page for **every class** found in the source folder. Each child page appears in the nav tree under this folder.

### Syntax

The `children` value is an object mapping a **type** to a **list of names**:

```json
{
    "children": {
        "classes": "{{classes}}",
        "functions": "{{functions}}"
    }
}
```

You can also mix tag expansion with explicit names:

```json
{
    "children": {
        "classes": ["{{interfaces}}", "MySpecialClass"]
    }
}
```

### Supported child types

| Type | Generates |
|---|---|
| `classes` | Class pages with full docs (description, info, properties, methods) |
| `enums` | Same as classes, filtered to enums |
| `dataclasses` | Same, filtered to dataclasses |
| `interfaces` | Same, filtered to interfaces/ABCs |
| `protocols` | Same, filtered to protocols |
| `exceptions` | Same, filtered to exceptions |
| `plain_classes` | Same, filtered to plain classes |
| `functions` | Function pages grouped by source file, with summary table and detail blocks |

### Auto-generated class page content

Each auto-generated class page contains (empty sections are automatically hidden):

```
# ClassName

(class description)

## Info
(module, file:line, base classes)

## Properties
(table of @property methods -- hidden if none)

## Public Methods
(summary table with links -- hidden if none)

## Private Methods
(summary table -- hidden if none)

## Method Details
(full signature, parameters, returns, raises for each method)
```

---

## Presentation Functions

Presentation functions render structured data tables and detail blocks from your source code. Write them as `%function_name(args)%` in the page body.

### Table functions

| Function | Output |
|---|---|
| `%classes_table({{classes}})%` | Table of classes with descriptions. Class names are cross-links |
| `%functions_table({{functions}})%` | Table of functions with signatures and descriptions |
| `%constants_table({{constants}})%` | Table of constants with values and types |

The argument can be a `{{tag}}` (expands to all matching items), a comma-separated list of names, or empty (uses all).

### Class detail functions

| Function | Output |
|---|---|
| `%class_description(ClassName)%` | Short + full description |
| `%class_info(ClassName)%` | Table: module, file:line, base classes |
| `%properties(ClassName)%` | Table of `@property` methods: name, type, description |
| `%base_classes(ClassName)%` | Comma-separated list of base classes |
| `%decorators(ClassName)%` | Comma-separated list of decorators |
| `%source_link(ClassName)%` | Source file path and line number |

### Methods functions

| Function | Output |
|---|---|
| `%methods_table(ClassName)%` | Public methods summary table |
| `%methods_table(ClassName, private)%` | Private methods (`_name`) table |
| `%methods_table(ClassName, static)%` | Static methods table |
| `%methods_table(ClassName, classmethod)%` | Class methods table |
| `%methods_table(ClassName, dunder)%` | Dunder methods (`__name__`) table |
| `%methods_table(ClassName, all)%` | All methods (public + private, including dunder) |
| `%methods_details(ClassName)%` | Full detail blocks for all methods: signature, params, returns, raises |

### PDF embedding

| Function | Output |
|---|---|
| `%pdf(path/to/file.pdf)%` | Embeds a PDF file as an inline viewer (iframe). The PDF is copied to the output directory automatically |

The path is relative to the parent of the docs root (same as `py_source`).

### Example page

```markdown
{
    "title": "API Reference",
    "py_source": "../src/mypackage"
}

# API Reference

## Classes

%classes_table({{classes}})%

## Functions

%functions_table({{functions}})%

## Constants

%constants_table({{constants}})%
```

---

## Cross-Links

Link to any class or method page from anywhere in your documentation using `[[double bracket]]` syntax.

| Syntax | Links to |
|---|---|
| `[[folder/ClassName]]` | Class page |
| `[[folder/ClassName.method_name]]` | Method anchor on the class page |
| `[[folder/ClassName\|Display Text]]` | Class page with custom display text |

The `folder` is the **basename** of the source folder. For example, if `py_source` is `../src/mypackage`, the folder slug is `mypackage`.

```markdown
See the [[mypackage/DataSource]] class for details.

The [[mypackage/DataSource.fetch]] method handles data retrieval.

Check [[mypackage/DataSource|the data source]] documentation.
```

### Hidden class pages

Every class in an indexed source folder automatically gets a dedicated page, even if not explicitly listed in `children`. These "hidden" pages:

- Are rendered with full class documentation
- Are indexed for cross-link resolution
- Appear in search results
- Do **not** appear in the navigation tree

This means `[[folder/AnyClass]]` always resolves, as long as the class exists in a parsed source folder.

---

## Markdown Links (`.md` → `.html`)

Standard markdown links to `.md` files are automatically rewritten to point to the correct `.html` output paths during build:

```markdown
[Data Engine](./DATA_ENGINE.md)              <!-- relative to current file -->
[Data Engine](DATA_ENGINE.md)                <!-- global search by filename -->
[Feature Engine](DATA_ENGINE.md#anchor)      <!-- with anchor -->
[API Docs](api/)                             <!-- folder link -> api/index.html -->
[API Section](api/#some-section)             <!-- folder link with anchor -->
```

### Resolution order

1. **Relative to current file** — standard relative path resolution (e.g. `./sibling.md`, `../other/page.md`)
2. **By filename globally** — if not found relative, searches the entire docs tree by filename

If multiple files share the same name, the global search produces a **build error** with a message to use a relative path instead.

### Folder links

Links ending with `/` are treated as folder references — `root.md` is appended automatically:

```markdown
[API Reference](api/)           <!-- resolves to api/root.md -> api/index.html -->
[API Section](api/#heading)     <!-- with anchor -->
```

---

## Docstring Format

slop-doc parses **Google-style** docstrings:

```python
class MyClass(BaseClass):
    """Short description of the class.

    Longer description that provides more detail
    about the class and its purpose.
    """

    def my_method(self, name: str, count: int = 5) -> list[str]:
        """Short description of the method.

        More detailed description here.

        Args:
            name: The name to process.
            count: How many times to repeat. Defaults to 5.

        Returns:
            A list of processed strings.

        Raises:
            ValueError: If name is empty.
            TypeError: If count is not an integer.
        """
```

### What gets parsed

- **Classes**: all public classes (private `_ClassName` are skipped)
- **Methods**: all methods including private and dunder, with full signatures
- **Functions**: top-level functions only (private and dunder are skipped)
- **Constants**: `ALL_CAPS` names assigned at module level
- **Properties**: methods decorated with `@property`
- **Type annotations**: preserved from source, displayed in method signatures and tables

### Class classification

Classes are automatically classified based on their base classes and decorators:

| Category | Detection rule |
|---|---|
| Enum | Inherits from `Enum`, `IntEnum`, `StrEnum`, `Flag`, `IntFlag` |
| Dataclass | Has `@dataclass` decorator |
| Interface/ABC | Inherits from `ABC`/`ABCMeta` or has any `@abstractmethod` |
| Protocol | Inherits from `Protocol` |
| Exception | Inherits from `Exception`/`BaseException` or name ends with `Error`/`Exception` |
| Plain class | None of the above |

---

## File Sorting

Files are sorted in the nav tree by:

1. **`order` front-matter field first**: pages with `"order": N` appear before unordered pages, sorted ascending by N
2. **Numeric prefix second**: `1-intro.md`, `2-setup.md`, `3-api.md` — sorted by number
3. **Alphabetical third**: files without numeric prefix or order sort alphabetically

The numeric prefix is stripped from the display title: `1-introduction.md` shows as "Introduction".

Example using `order`:

```markdown
{
    "title": "Getting Started",
    "order": 1
}
```

---

## Settings

All settings are optional and have safe defaults. Configure them in the root `root.md` front-matter.

### `editor`

Editor URI scheme for double-click-to-open-source. Double-clicking the content area opens the source `.md` file in the configured editor.

```json
{ "editor": "vscode" }
```

Supported values: `"vscode"`, `"vscodium"`, `"cursor"`, or any editor that supports `<scheme>://file/<path>` URIs. Empty string (default) disables the feature.

### `exclude_dirs`

Extra directory names to skip when scanning the docs folder. Useful for draft or archive folders you don't want in the build.

```json
{ "exclude_dirs": ["drafts", "archive"] }
```

The output directory is always excluded automatically.

### `max_search_results`

Maximum number of results shown in the search dropdown. Default: `12`.

```json
{ "max_search_results": 8 }
```

### `default_collapsed`

If `true`, the navigation tree starts fully collapsed on first visit (before the user has manually expanded anything). Once the user interacts with the nav, their expand/collapse state is persisted in localStorage and takes priority.

```json
{ "default_collapsed": true }
```

### `port`

Default port for `slop-doc start`. Overridden by the CLI `-p` flag. Default: `8000`.

```json
{ "port": 9000 }
```

---

## Agent Instruction File

`slop-doc-instruction.md` is a concise reference file created next to the docs folder. It is designed for AI agents and LLMs — a compact summary of all slop-doc features, syntax, and conventions.

- **Created** on `slop-doc init` next to the docs folder
- **Auto-updated** on every `build` / `start` when the slop-doc version changes (tracked via `<!-- slop-doc-version: X.X -->` comment)
- **No manual maintenance** — always stays in sync with the installed slop-doc version

---

## Assets and Styling

slop-doc ships with a default dark theme (`style.css`) and client-side app (`app.js`).

The app provides:

- **SPA navigation** — internal links are fetched and swapped without full page reload (falls back to normal navigation on `file://` or fetch failure)
- **Smooth transitions** — content fade-in on page switch
- **Client-side search** — search index is embedded inline in each page (no server required)
- **Scroll spy** — right sidebar highlights the current section on scroll
- **Anchor highlight** — clicking an anchor link smoothly scrolls and flashes the target element
- **Nav tree persistence** — expand/collapse state is saved in localStorage across page loads
- **PDF viewer** — inline PDF embedding via `%pdf()%` presentation function
- **Editor integration** — double-click content area to open source file in your editor

To customize styling:

1. Set `assets_dir` in your root `root.md`:
   ```json
   {
       "assets_dir": "assets"
   }
   ```

2. Place your custom `style.css` in that folder. It will replace the default.

The `app.js` is always copied from defaults (the search index is embedded inline in each page).

---

## Complete Example

### Project structure

```
my-project/
+-- src/
|   +-- mylib/
|       +-- __init__.py
|       +-- client.py        # Client, Config classes
|       +-- models.py         # User, Product dataclasses
|       +-- exceptions.py     # ApiError, NotFoundError
+-- docs/
    +-- root.md
    +-- 1-getting-started.md
    +-- guides/              # no root.md = container node in nav
    |   +-- tutorial.md
    |   +-- faq.md
    +-- api/
        +-- root.md
        +-- overview.md
```

### docs/root.md

```markdown
{
    "title": "MyLib",
    "project_name": "MyLib",
    "version": "1.0.0",
    "output_dir": "build",
    "editor": "vscode"
}

# MyLib Documentation

Welcome to the MyLib documentation.
```

### docs/1-getting-started.md

```markdown
# Getting Started

## Installation

```bash
pip install mylib
```

## Quick Start

```python
from mylib import Client

client = Client(api_key="...")
result = client.fetch("data")
```
```

### docs/api/root.md

```markdown
{
    "title": "API Reference",
    "py_source": "../../src/mylib",
    "children": {
        "classes": "{{classes}}"
    }
}

# API Reference

## All Classes

%classes_table({{classes}})%

## Functions

%functions_table({{functions}})%

## Constants

%constants_table({{constants}})%
```

This generates:
- A nav tree: Getting Started, Guides > Tutorial + FAQ, API Reference > Client, Config, User, Product, ApiError, NotFoundError
- The "Guides" node is a container — clicking it toggles children, no page is generated
- Each class gets a full page with methods, properties, signatures
- Cross-links like `[[mylib/Client]]` work from any page

### Build and view

```bash
cd docs
slop-doc build        # one-off build
slop-doc start        # build + serve + live reload
```

---

## Output Structure

```
docs/build/
+-- index.html              <- root.md landing page
+-- getting-started.html
+-- guides/
|   +-- tutorial.html
|   +-- faq.html
+-- api/
|   +-- index.html          <- api/root.md
|   +-- client.html         <- auto-generated from children
|   +-- config.html
|   +-- user.html
|   +-- ...
+-- assets/
    +-- style.css
    +-- app.js
```

---

## Summary of Syntax

| Syntax | Where | Purpose |
|---|---|---|
| `{ "key": "value" }` | Top of `.md` file | Front-matter config |
| `{{tag}}` | Page body or `children` value | Expand to list of items from source |
| `{{tag_rec}}` | Page body or `children` value | Same but recursive (includes subfolders) |
| `%function(args)%` | Page body | Render tables/details from source data |
| `%pdf(path/to/file.pdf)%` | Page body | Embed a PDF file inline |
| `[[folder/Class]]` | Page body | Cross-link to class page |
| `[[folder/Class.method]]` | Page body | Cross-link to method anchor |
| `[[folder/Class\|text]]` | Page body | Cross-link with custom display text |
| `[text](file.md)` | Page body | Link to another `.md` page (auto-resolved to `.html`) |
| `[text](file.md#anchor)` | Page body | Link to anchor in another page |
| `[text](folder/)` | Page body | Link to folder's `root.md` page |

---

## Architecture

### Modules

| Module | Purpose |
|---|---|
| `builder.py` | Build orchestrator — drives the full pipeline, CLI commands (`init`, `build`, `start`), live-reload server, `.md` link rewriting, instruction file sync |
| `watcher.py` | File watcher — monitors docs folder for changes, debounced rebuild via `watchdog` |
| `tree_builder.py` | Walks the docs folder, builds the navigation tree of `Node` objects |
| `frontmatter.py` | Parses relaxed JSON front-matter from `.md` files |
| `parser.py` | Python AST source parser — extracts classes, functions, constants, docstrings |
| `tag_renderer.py` | Expands `{{data tags}}` and `%presentation functions%` into HTML |
| `cross_links.py` | Builds cross-link index and resolves `[[Target]]` patterns |
| `markdown_renderer.py` | Converts Markdown to HTML, adds heading anchors |
| `layout.py` | Assembles 3-column HTML pages: nav tree, content, contents sidebar |

### Build Pipeline

When `slop-doc build` runs, the following steps execute in order:

```
1. Sync instruction file
   +-- Create/update slop-doc-instruction.md next to docs folder (if version changed)

2. Read project config
   +-- Parse root.md front-matter -> project_name, version, output_dir, settings

3. Build navigation tree
   +-- Recursively walk docs folder (tree_builder.py)
      +-- Parse each .md front-matter + body
      +-- Resolve py_source (inherited down the tree)
      +-- Expand children: generators ({{classes}}, {{functions}}, etc.)
      +-- Parse Python source folders on demand (cached)
      +-- Create container nodes for folders without root.md
      +-- Sort nodes: order field -> numeric prefix -> alphabetical

4. Build .md link map
   +-- Map md filenames -> html output paths (for .md link rewriting)

5. Build cross-link index
   +-- Walk tree, index every class page URL + method anchors

6. Generate search index
   +-- Walk tree, collect all pages/classes/methods/functions/constants -> JSON

7. Render each page
   |  For each node in the tree:
   |
   +-- Auto-class pages -> generate Markdown body from presentation functions
   +-- Auto-function pages -> grouped by source file with summary + details
   +-- Regular pages -> use .md file content
   +-- Container nodes -> skipped (no page generated)
   +-- Empty folders with children -> simple "# Title" placeholder
   |
   +-- Page rendering pipeline:
      a. Expand %presentation_functions(args)%  ->  HTML tables/details
      b. Expand remaining {{data_tags}}         ->  cross-links or inline text
      c. Strip empty sections                   ->  remove headings with no content
      d. Markdown -> HTML                       ->  via python-markdown
      e. Rewrite .md links                      ->  resolve .md hrefs to .html output paths
      f. Resolve [[cross-links]]                ->  relative <a href> tags
      g. Assemble full HTML page                ->  3-column layout with nav, breadcrumb, search index, settings

8. Copy assets
   +-- User assets (override) -> default style.css (fallback) -> app.js (always from defaults)
   +-- Copy referenced PDF files to output directory
```

### Source Parsing

`parser.py` uses Python's `ast` module to extract structured data from `.py` files:

- **Classes**: name, base classes, decorators, docstring, properties, methods, classification (enum / dataclass / interface / protocol / exception / plain)
- **Functions**: name, args (with types + defaults), return type, decorators, docstring
- **Constants**: `ALL_CAPS` module-level assignments with values and types
- **Docstrings**: Google-style parsing — `Args:`, `Returns:`, `Raises:`, `Examples:` sections

Two scopes per folder:
- **Flat** — only direct `.py` files (used by `{{classes}}`, `{{functions}}`, etc.)
- **Recursive** — includes all subfolders (used by `{{classes_rec}}`, `{{functions_rec}}`, etc.)

### Tree Structure

Each node in the tree is a `Node` dataclass:

```
Node
+-- title              display title
+-- content            markdown body (from .md file)
+-- source             path to Python source folder
+-- output_path        relative output path (e.g. api/client.html), empty for container nodes
+-- children           list of child Nodes
+-- order              explicit sort order (from front-matter)
+-- is_auto            true for auto-generated pages
+-- auto_class         class name (for auto class pages)
+-- auto_function      function name (for function nav nodes)
+-- auto_source_file   source file basename (for file-function pages)
+-- md_source_path     absolute path to source .md file
+-- meta               PageMeta from front-matter
```

Folder structure maps directly to the nav tree:
- `root.md` in a folder -> folder node config + landing page
- Other `.md` files -> child pages
- Subfolders with `root.md` -> nested folder nodes
- Subfolders without `root.md` but with `.md` files -> container nodes (nav grouping only)
- `children` front-matter -> auto-generated class/function pages

### HTML Output

Each page is a self-contained HTML file with embedded search index and settings:

```html
<header>  project name | breadcrumb | search input  </header>

<nav class="sidebar-left">     <- navigation tree (persistent expand/collapse state)
<main class="content">          <- rendered page content
<aside class="sidebar-right">   <- table of contents (h2/h3 headings, scroll spy)

<script src="assets/app.js">    <- SPA navigation, search, scroll spy, PDF viewer, editor integration
<script>                         <- embedded settings, search index + prefix (inline, no CORS issues)
```

### Client-Side App (`app.js`)

The app runs entirely client-side with no build step or dependencies:

- **SPA navigation**: intercepts internal link clicks, fetches pages via `fetch()`, swaps `.content` / sidebar / breadcrumb / nav / settings without full reload. Falls back to normal navigation on `file://` or fetch failure
- **Search**: filters embedded `__SEARCH_INDEX__` by title substring, renders dropdown (limit configurable via `max_search_results`)
- **Scroll spy**: highlights current section in the right sidebar on scroll
- **Nav tree**: expand/collapse with localStorage persistence, animated via `max-height` CSS transitions. Optionally starts collapsed (`default_collapsed` setting)
- **Anchor navigation**: smooth scroll + highlight flash animation on target element
- **Sidebar sync**: `ResizeObserver` keeps content margin aligned with dynamic sidebar width
- **History**: `pushState` / `popstate` for browser back/forward support within SPA
- **PDF viewer**: renders `%pdf()%` embeds as full-width iframes
- **Editor integration**: double-click on content area opens source `.md` in configured editor (`editor` setting)

## License

MIT
