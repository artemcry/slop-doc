"""Stage 2: SDOC Preprocessor - expands macros in .sdoc files before YAML parsing."""

from __future__ import annotations

import re


class SDOCPreprocessorError(Exception):
    """Raised when macro preprocessing fails."""
    pass


def expand_macros(sdoc_text: str, class_names: list[str] = None, function_names: list[str] = None) -> str:
    """Expand macros in SDOC text before YAML parsing.

    Args:
        sdoc_text: Raw SDOC text with potential macros.
        class_names: List of class names found in the source folder.
        function_names: List of function names found in the source folder.

    Returns:
        Valid YAML string with all macros expanded.

    Raises:
        SDOCPreprocessorError: If an unknown macro is encountered.
    """
    class_names = class_names or []
    function_names = function_names or []

    result = sdoc_text

    # Process CLASSES blocks
    result = _expand_class_blocks(result, class_names)

    # Process FUNCTIONS blocks
    result = _expand_function_blocks(result, function_names)

    # Final check for any remaining unknown macros
    validate_no_unknown_macros(result)

    return result


def _expand_class_blocks(text: str, class_names: list[str]) -> str:
    """Expand %%__CLASSES%% blocks in text."""
    # Pattern to match class macro blocks - both plain and .exclude() variants
    pattern = r'%%__CLASSES__(?:\.exclude\([^)]*\))?%%(.*?)%%__CLASSES__(?:\.exclude\([^)]*\))?%%'

    def replace_block(match):
        opening_tag = match.group(0)
        inner = match.group(1)

        # Check for .exclude() modifier in the opening tag
        exclude_match = re.search(r'\.exclude\(([^)]*)\)', opening_tag)
        if exclude_match:
            excluded = [name.strip() for name in exclude_match.group(1).split(',')]
            filtered_classes = [c for c in class_names if c not in excluded]
        else:
            filtered_classes = class_names

        # Expand the inner block for each class
        expanded_lines = []
        for cls_name in filtered_classes:
            # Replace %%__CLASS__%% with the class name in each line
            expanded_line = inner.replace('%%__CLASS__%%', cls_name)
            expanded_lines.append(expanded_line)

        return '\n'.join(expanded_lines)

    # First, remove all known CLASSES blocks to get clean text for checking
    temp_text = re.sub(pattern, '', text, flags=re.DOTALL)

    # Now check for unknown macros in what remains
    # Match %%__CLASS...%% (but not __CLASSES__ or __CLASSES.exclude)
    unknown_class_pattern = r'%%__CLASS[A-Z_]*%%'
    if re.search(unknown_class_pattern, temp_text):
        raise SDOCPreprocessorError(
            f"Unknown macro found. Valid macros are: __CLASSES__, __FUNCTIONS__"
        )

    return re.sub(pattern, replace_block, text, flags=re.DOTALL)


def _expand_function_blocks(text: str, function_names: list[str]) -> str:
    """Expand %%__FUNCTIONS%% blocks in text."""
    # Pattern to match function macro blocks - both plain and .exclude() variants
    pattern = r'%%__FUNCTIONS__(?:\.exclude\([^)]*\))?%%(.*?)%%__FUNCTIONS__(?:\.exclude\([^)]*\))?%%'

    def replace_block(match):
        opening_tag = match.group(0)
        inner = match.group(1)

        # Check for .exclude() modifier
        exclude_match = re.search(r'\.exclude\(([^)]*)\)', opening_tag)
        if exclude_match:
            excluded = [name.strip() for name in exclude_match.group(1).split(',')]
            filtered_funcs = [f for f in function_names if f not in excluded]
        else:
            filtered_funcs = function_names

        # Expand the inner block for each function
        expanded_lines = []
        for func_name in filtered_funcs:
            expanded_line = inner.replace('%%__FUNCTION__%%', func_name)
            expanded_lines.append(expanded_line)

        return '\n'.join(expanded_lines)

    # First, remove all known FUNCTIONS blocks to get clean text for checking
    temp_text = re.sub(pattern, '', text, flags=re.DOTALL)

    # Now check for unknown macros in what remains
    unknown_func_pattern = r'%%__FUNCTION[A-Z_]*%%'
    if re.search(unknown_func_pattern, temp_text):
        raise SDOCPreprocessorError(
            f"Unknown macro found. Valid macros are: __CLASSES__, __FUNCTIONS__"
        )

    return re.sub(pattern, replace_block, text, flags=re.DOTALL)


def validate_no_unknown_macros(text: str) -> None:
    """Check for unknown macros and raise error if found.

    Args:
        text: The SDOC text to check.

    Raises:
        SDOCPreprocessorError: If an unknown macro is found.
    """
    # Match any %%__...%% pattern that isn't a known macro
    known_macros = ['__CLASSES__', '__FUNCTIONS__']
    all_macro_pattern = r'%%__([A-Z_]+)%%'

    for match in re.finditer(all_macro_pattern, text):
        macro_name = match.group(1)
        if macro_name not in known_macros:
            raise SDOCPreprocessorError(
                f"Unknown macro '{macro_name}'. Valid macros are: __CLASSES__, __FUNCTIONS__"
            )