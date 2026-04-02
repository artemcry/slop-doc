"""Tests for Stage 2: SDOC Preprocessor."""

import pytest
from slop_doc.sdoc_preprocessor import expand_macros, SDOCPreprocessorError


class TestExpandClassesBasic:
    """Test basic %%__CLASSES__%% expansion."""

    def test_expand_classes_basic(self):
        sdoc = '''
children:
  %%__CLASSES__%%
  - title: "%%__CLASS__%% Class"
    template: "default_class"
    params:
      CLASS_ID: "%%__CLASS__%%"
  %%__CLASSES__%%
'''
        result = expand_macros(sdoc, class_names=["Pipeline", "SourceNode"])
        assert '- title: "Pipeline Class"' in result
        assert '- title: "SourceNode Class"' in result
        assert 'CLASS_ID: "Pipeline"' in result
        assert 'CLASS_ID: "SourceNode"' in result

    def test_expand_classes_exclude(self):
        sdoc = '''
children:
  %%__CLASSES__.exclude(SourceNode)%%
  - title: "%%__CLASS__%% Class"
    template: "default_class"
  %%__CLASSES__.exclude(SourceNode)%%
'''
        result = expand_macros(sdoc, class_names=["Pipeline", "SourceNode", "SinkNode"])
        assert '- title: "Pipeline Class"' in result
        assert '- title: "SinkNode Class"' in result
        assert "SourceNode" not in result

    def test_expand_no_classes(self):
        sdoc = '''
children:
  %%__CLASSES__%%
  - title: "%%__CLASS__%% Class"
    template: "default_class"
  %%__CLASSES__%%
'''
        result = expand_macros(sdoc, class_names=[])
        # The block should be removed entirely (empty result)
        assert "Pipeline" not in result
        assert "Class" not in result

    def test_mixed_content(self):
        """Manual children should be preserved with expanded macros in between."""
        sdoc = '''
children:
  - title: "Manual Page"
    template: "manual"
  %%__CLASSES__%%
  - title: "%%__CLASS__%% Class"
    template: "default_class"
  %%__CLASSES__%%
  - title: "Another Manual"
    template: "another"
'''
        result = expand_macros(sdoc, class_names=["Pipeline"])
        assert '- title: "Manual Page"' in result
        assert '- title: "Pipeline Class"' in result
        assert '- title: "Another Manual"' in result

        # Check order
        manual_pos = result.find('Manual Page')
        pipeline_pos = result.find('Pipeline Class')
        another_pos = result.find('Another Manual')
        assert manual_pos < pipeline_pos < another_pos

    def test_no_macros(self):
        """SDOC without macros should be returned unchanged."""
        sdoc = '''
children:
  - title: "Manual Page"
    template: "manual"
'''
        result = expand_macros(sdoc, class_names=["Pipeline"])
        assert result == sdoc


class TestExpandFunctions:
    """Test %%__FUNCTIONS__%% expansion."""

    def test_expand_functions(self):
        sdoc = '''
children:
  %%__FUNCTIONS__%%
  - title: "%%__FUNCTION__%%()"
    template: "default_function"
    params:
      FUNC_ID: "%%__FUNCTION__%%"
  %%__FUNCTIONS__%%
'''
        result = expand_macros(sdoc, function_names=["run", "stop"])
        assert '- title: "run()"' in result
        assert '- title: "stop()"' in result
        assert 'FUNC_ID: "run"' in result

    def test_expand_functions_exclude(self):
        sdoc = '''
children:
  %%__FUNCTIONS__.exclude(stop)%%
  - title: "%%__FUNCTION__%%"
    template: "default_function"
  %%__FUNCTIONS__.exclude(stop)%%
'''
        result = expand_macros(sdoc, function_names=["run", "stop", "pause"])
        assert "run" in result
        assert "stop" not in result
        assert "pause" in result


class TestInvalidMacroName:
    """Test handling of invalid macro names."""

    def test_invalid_macro_name(self):
        sdoc = '''
children:
  %%__INVALID__%%
  - title: "Test"
  %%__INVALID__%%
'''
        with pytest.raises(SDOCPreprocessorError) as exc_info:
            expand_macros(sdoc, class_names=["Pipeline"])
        assert "Unknown macro" in str(exc_info.value)


class TestValidYamlOutput:
    """Test that output is valid YAML."""

    def test_valid_yaml_output(self):
        """Expanded output should parse as valid YAML."""
        import yaml
        sdoc = '''
branch: "API Reference"
title: "DataFlow"
template: "default_module"
source: "."
children:
  %%__CLASSES__.exclude(InternalHelper)%%
  - title: "%%__CLASS__%% Class"
    template: "default_class"
    params:
      CLASS_ID: "%%__CLASS__%%"
  %%__CLASSES__.exclude(InternalHelper)%%
'''
        result = expand_macros(sdoc, class_names=["Pipeline", "SourceNode", "InternalHelper"])

        # Should not raise - output is valid YAML
        parsed = yaml.safe_load(result)
        assert parsed is not None
        # Check structure
        children = parsed.get('children', [])
        # Should have 2 children (Pipeline and SourceNode classes)
        assert len(children) == 2

    def test_exclude_multiple(self):
        """Test excluding multiple classes."""
        sdoc = '''
children:
  %%__CLASSES__.exclude(InternalHelper, BaseClass)%%
  - title: "%%__CLASS__%%"
    template: "default_class"
  %%__CLASSES__.exclude(InternalHelper, BaseClass)%%
'''
        result = expand_macros(sdoc, class_names=["Pipeline", "InternalHelper", "BaseNode", "BaseClass"])
        assert "Pipeline" in result
        assert "InternalHelper" not in result
        assert "BaseNode" in result
        assert "BaseClass" not in result


class TestEdgeCases:
    """Test edge cases."""

    def test_class_with_underscores(self):
        """Classes with underscores should work."""
        sdoc = '''
children:
  %%__CLASSES__%%
  - title: "%%__CLASS__%%"
    template: "default_class"
  %%__CLASSES__%%
'''
        result = expand_macros(sdoc, class_names=["BaseNode", "_InternalClass"])
        assert "BaseNode" in result
        assert "_InternalClass" in result

    def test_empty_exclude(self):
        """%%__CLASSES__.exclude()%% with empty parens should not exclude anything."""
        sdoc = '''
children:
  %%__CLASSES__.exclude()%%
  - title: "%%__CLASS__%%"
    template: "default_class"
  %%__CLASSES__.exclude()%%
'''
        result = expand_macros(sdoc, class_names=["Pipeline", "SourceNode"])
        assert "Pipeline" in result
        assert "SourceNode" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])