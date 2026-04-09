<!-- slop-doc-version: __VERSION__ -->
# slop-doc — Agent Reference

Static doc generator: `.md` files + Python AST parsing -> 3-column HTML site with nav tree, search, cross-links.

## CLI

```bash
slop-doc init [--name docs]       # scaffold docs/ with root.md + slop-doc-instruction.md
slop-doc build [-d docs]          # build HTML site
slop-doc start [-d docs] [-p 8000] [-o] # build + serve + live reload (-o to open browser)
```

`slop-doc-instruction.md` is auto-created next to docs folder on `init`/`build`/`start` and auto-updated when slop-doc version changes.

## Docs Folder = Nav Tree

```
docs/
  root.md              <- REQUIRED. Project config + landing page -> build/index.html
  getting-started.md   <- page -> build/getting-started.html
  api/
    root.md            <- folder node config -> build/api/index.html
  data/
    root.md            <- {} only (no body) = container node with frontmatter (no page)
    overview.md
  guides/              <- NO root.md = container node (nav grouping only, no page)
    tutorial.md
```

- `root.md` with content = folder node (has a page)
- `root.md` with only frontmatter (no body) = container node with config (no page, but frontmatter like `py_source`, `children`, `order` still works)
- Folder without `root.md` = container node (toggle children in nav, no page generated)
- Title: frontmatter `title` > first `# heading` > cleaned filename (numeric prefix stripped)

## Frontmatter

JSON block at top of `.md` file. Supports `//` comments, trailing commas, unquoted keys.

### Page keys

| Key | Type | Description |
|---|---|---|
| `title` | string | Nav display name |
| `py_source` | string | Path to Python source folder. Resolved relative to **parent of docs root**. Inherited by children — set once on folder `root.md` |
| `children` | object | Auto-generate child pages from source. See Children section |
| `order` | int | Sort position in nav (lower first). Unordered pages come after ordered ones |

### Project keys (root `root.md` only)

| Key | Default | Description |
|---|---|---|
| `project_name` | `"Documentation"` | Site header title |
| `version` | `""` | Shown in page titles |
| `output_dir` | `"build"` | Output folder relative to docs root |
| `assets_dir` | — | Custom assets folder (custom `style.css` overrides default) |
| `editor` | `""` | Editor URI scheme: `"vscode"`, `"vscodium"`, `"cursor"`. Empty = disabled |
| `exclude_dirs` | `[]` | Folder names to skip when scanning docs |
| `max_search_results` | `12` | Search dropdown limit |
| `default_collapsed` | `false` | Nav tree starts collapsed on first visit |
| `port` | `8000` | Default port for `slop-doc start` |

### Example root.md

```markdown
{
    "title": "MyLib Docs",
    "project_name": "MyLib",
    "version": "1.0",
    "output_dir": "build",
    "py_source": "../src/mylib",
    "editor": "vscode"
}

# Welcome to MyLib

Landing page content.
```

## Markdown Links `.md` -> `.html`

Standard markdown links to `.md` files are auto-resolved to their `.html` output paths:

```markdown
[Data Engine](./DATA_ENGINE.md)              # relative to current file
[Data Engine](DATA_ENGINE.md)                # global search by filename
[Feature Engine](DATA_ENGINE.md#anchor)      # with anchor
[API Docs](api/)                             # folder link -> api/index.html
[API Section](api/#some-section)             # folder link with anchor
```

Resolution order:
1. Relative to current file
2. By filename across entire docs tree (build error if ambiguous — use relative path to disambiguate)

## Data Tags `{{tag}}`

Expand to lists of items from Python source. Use in page body or in `children` values.

| Tag | Scope | Items |
|---|---|---|
| `{{classes}}` | flat | Classes |
| `{{functions}}` | flat | Functions |
| `{{constants}}` | flat | Constants (ALL_CAPS) |
| `{{enums}}` | recursive | Enum classes |
| `{{dataclasses}}` | recursive | Dataclass classes |
| `{{interfaces}}` | recursive | ABC/abstract classes |
| `{{protocols}}` | recursive | Protocol classes |
| `{{exceptions}}` | recursive | Exception classes |
| `{{plain_classes}}` | recursive | Classes not in any category above |

**Flat** = direct `.py` files in source folder only. **Recursive** = includes subfolders.

Any tag + `_rec` suffix = recursive variant: `{{classes_rec}}`, `{{functions_rec}}`, `{{constants_rec}}`.

In body text, class tags render as cross-linked names; other tags render as code spans. Empty = *None found.*

## Children (Auto-Generated Pages)

The `children` frontmatter key generates child pages from source code:

```json
{
    "children": {
        "classes": "{{classes}}",
        "functions": "{{functions}}"
    }
}
```

Each class gets a full page (description, info table, properties, methods table, method details). Functions are grouped by source file into one page per file.

Supported types: `classes`, `enums`, `dataclasses`, `interfaces`, `protocols`, `exceptions`, `plain_classes`, `functions`.

You can mix tags with explicit names:
```json
{ "children": { "classes": ["{{interfaces}}", "SpecificClass"] } }
```

## Presentation Functions `%func(args)%`

Render structured HTML from source data. Use in page body.

### Tables

| Function | Output |
|---|---|
| `%classes_table({{classes}})%` | Table of classes with descriptions (cross-linked names) |
| `%functions_table({{functions}})%` | Table of functions with signatures |
| `%constants_table({{constants}})%` | Table of constants with values and types |

Argument: `{{tag}}`, comma-separated names, or empty (= all).

### Class details

| Function | Output |
|---|---|
| `%class_description(Name)%` | Short + full description |
| `%class_info(Name)%` | Module, file:line, base classes table |
| `%properties(Name)%` | Properties table (name, type, description) |
| `%base_classes(Name)%` | Comma-separated base classes |
| `%decorators(Name)%` | Comma-separated decorators |
| `%source_link(Name)%` | Source file path and line number |

### Methods

| Function | Output |
|---|---|
| `%methods_table(Name)%` | Public methods summary table |
| `%methods_table(Name, private)%` | Private methods (`_name`) table |
| `%methods_table(Name, static)%` | Static methods |
| `%methods_table(Name, classmethod)%` | Class methods |
| `%methods_table(Name, dunder)%` | Dunder methods (`__name__`) |
| `%methods_table(Name, all)%` | All methods |
| `%methods_details(Name)%` | Full detail blocks: signature, params, returns, raises |

### Other

| Function | Output |
|---|---|
| `%pdf(path/to/file.pdf)%` | Inline PDF viewer (path relative to parent of docs root) |

## Cross-Links `[[target]]`

| Syntax | Links to |
|---|---|
| `[[folder/ClassName]]` | Class page |
| `[[folder/ClassName.method]]` | Method anchor on class page |
| `[[folder/ClassName\|Display Text]]` | Custom display text |

`folder` = basename of the `py_source` path. If `py_source` is `../src/mylib`, use `mylib`.

Every class in a parsed source folder is indexed for cross-linking, even if not in `children` (hidden pages — no nav entry, but searchable and linkable).

## Docstring Format

Google-style with `Args:`, `Returns:`, `Raises:`, `Examples:` sections:

```python
def fetch(self, url: str, timeout: int = 30) -> Response:
    """Fetch data from URL.

    Args:
        url: Target URL.
        timeout: Request timeout in seconds.

    Returns:
        Response object with data.

    Raises:
        ConnectionError: If unreachable.
    """
```

## Class Classification

| Category | Detection |
|---|---|
| Enum | Base class: `Enum`, `IntEnum`, `StrEnum`, `Flag`, `IntFlag` |
| Dataclass | `@dataclass` decorator |
| Interface | Base: `ABC`/`ABCMeta` or has `@abstractmethod` |
| Protocol | Base: `Protocol` |
| Exception | Base: `Exception`/`BaseException` or name ends with `Error`/`Exception` |
| Plain | None of the above |

## Sorting

1. `order` frontmatter (ascending) — ordered pages come first
2. Numeric filename prefix (`1-intro.md` before `2-setup.md`) — prefix stripped from title
3. Alphabetical

## Build Pipeline

```
root.md config -> tree_builder (walk docs, expand children, inherit py_source)
  -> sync slop-doc-instruction.md (create/update next to docs folder)
  -> parser (AST-parse Python source, cached per folder)
  -> build .md link map (md filename -> html output path)
  -> cross_links (index class/method URLs)
  -> layout (search index from all pages/classes/methods/functions/constants)
  -> per page: presentation functions -> data tags -> strip empty sections
     -> markdown -> HTML -> rewrite .md links -> resolve cross-links -> assemble 3-column layout
  -> copy assets (app.js always from defaults, style.css from assets_dir or defaults)
```

## Modules

| Module | Purpose |
|---|---|
| `builder.py` | CLI + build orchestrator, .md link rewriting, instruction file sync |
| `tree_builder.py` | Walks docs folder, builds Node tree, expands children |
| `frontmatter.py` | Relaxed JSON frontmatter parser |
| `parser.py` | Python AST parser (classes, functions, constants, docstrings) |
| `tag_renderer.py` | Expands `{{tags}}` and `%functions%` |
| `cross_links.py` | Cross-link index + `[[target]]` resolution |
| `markdown_renderer.py` | Markdown -> HTML with heading anchors |
| `layout.py` | 3-column HTML assembly, nav tree, search index, TOC sidebar |
| `watcher.py` | File watcher — debounced rebuild via watchdog for live reload |

## Output

Self-contained HTML site. Each page embeds search index + settings inline (no server needed). SPA navigation via `app.js` (falls back to normal links on `file://`). Dark theme by default.
