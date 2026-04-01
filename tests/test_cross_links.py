"""Tests for Stage 5: Cross-Link Index & Resolver."""

import pytest
from pydocgen.cross_links import (
    CrossLinkIndex, resolve_links, build_index, CrossLinkError, _get_folder_slug
)
from pydocgen.tree_builder import Node
from pydocgen.parser import SourceData, ClassData, FunctionData


class TestGetFolderSlug:
    """Test folder slug extraction from output paths."""

    def test_module_page(self):
        """api-reference/dataflow.html -> dataflow"""
        assert _get_folder_slug("api-reference/dataflow.html") == "dataflow"

    def test_class_page(self):
        """api-reference/dataflow/pipeline-class.html -> dataflow"""
        assert _get_folder_slug("api-reference/dataflow/pipeline-class.html") == "dataflow"

    def test_root_page(self):
        """introduction.html -> ''"""
        assert _get_folder_slug("introduction.html") == ""


class TestResolveClassLink:
    """Test resolving class links with mandatory folder/ClassName format."""

    def test_resolve_class_link(self):
        """See [[dataflow/Pipeline]], index has dataflow/Pipeline."""
        index = CrossLinkIndex()
        index.folder_class_index["dataflow/Pipeline"] = "/api-reference/dataflow/pipeline-class.html"

        text = "See [[dataflow/Pipeline]]"
        result = resolve_links(text, index)
        assert '<a href="/api-reference/dataflow/pipeline-class.html">Pipeline</a>' in result

    def test_resolve_method_link(self):
        """Call [[dataflow/Pipeline.run]]."""
        index = CrossLinkIndex()
        index.folder_class_index["dataflow/Pipeline"] = "/api-reference/dataflow/pipeline-class.html"

        text = "Call [[dataflow/Pipeline.run]]"
        result = resolve_links(text, index)
        assert "pipeline-class.html#run" in result

    def test_resolve_custom_text(self):
        """[[dataflow/Pipeline|the main class]]."""
        index = CrossLinkIndex()
        index.folder_class_index["dataflow/Pipeline"] = "/api-reference/dataflow/pipeline-class.html"

        text = "[[dataflow/Pipeline|the main class]]"
        result = resolve_links(text, index)
        assert 'href="/api-reference/dataflow/pipeline-class.html"' in result
        assert "the main class" in result

    def test_resolve_no_folder_raises_error(self):
        """[[Pipeline]] without folder should raise error."""
        index = CrossLinkIndex()

        text = "[[Pipeline]]"
        with pytest.raises(CrossLinkError) as exc:
            resolve_links(text, index)
        assert "Invalid cross-link format" in str(exc.value)
        assert "folder/ClassName" in str(exc.value)

    def test_resolve_not_found(self):
        """[[nonexistent/Pipeline]] should raise error."""
        index = CrossLinkIndex()

        text = "[[nonexistent/Pipeline]]"
        with pytest.raises(CrossLinkError) as exc:
            resolve_links(text, index)
        assert "not found" in str(exc.value)

    def test_no_links(self):
        """No links in text returns unchanged."""
        index = CrossLinkIndex()

        text = "No links here"
        result = resolve_links(text, index)
        assert result == text


class TestBuildIndex:
    """Test building the cross-link index."""

    def test_build_index_with_classes(self):
        """Index built from tree with class nodes uses folder_class_index."""
        tree = [
            Node(
                title="DataFlow",
                template="default_module",
                output_path="/api-reference/dataflow.html",
                source="/path/to/src/dataflow"
            )
        ]
        source_data = {
            "/path/to/src/dataflow": SourceData(
                classes=[
                    ClassData(name="Pipeline", short_description="A pipeline", full_description="", methods=[], decorators=[], base_classes=[], properties=[])
                ],
                functions=[],
                constants=[]
            )
        }

        index = build_index(tree, source_data)

        # Should have folder_class_index entry
        assert "dataflow/Pipeline" in index.folder_class_index
        assert index.folder_class_index["dataflow/Pipeline"] == "/api-reference/dataflow.html"

    def test_build_index_with_class_pages(self):
        """Index built with child class pages."""
        tree = [
            Node(
                title="DataFlow",
                template="default_module",
                output_path="/api-reference/dataflow.html",
                source="/path/to/src/dataflow",
                children=[
                    Node(
                        title="Pipeline Class",
                        template="default_class",
                        output_path="/api-reference/dataflow/pipeline-class.html",
                        source="/path/to/src/dataflow",
                        params={"CLASS_ID": "Pipeline"}
                    )
                ]
            )
        ]
        source_data = {
            "/path/to/src/dataflow": SourceData(
                classes=[
                    ClassData(name="Pipeline", short_description="A pipeline", full_description="", methods=[], decorators=[], base_classes=[], properties=[])
                ],
                functions=[],
                constants=[]
            )
        }

        index = build_index(tree, source_data)

        # Should have folder_class_index entry pointing to class page
        assert "dataflow/Pipeline" in index.folder_class_index
        assert index.folder_class_index["dataflow/Pipeline"] == "/api-reference/dataflow/pipeline-class.html"

    def test_build_index_with_methods(self):
        """Methods are indexed under folder/class format."""
        tree = [
            Node(
                title="DataFlow",
                template="default_module",
                output_path="/api-reference/dataflow.html",
                source="/path/to/src/dataflow",
                children=[
                    Node(
                        title="Pipeline Class",
                        template="default_class",
                        output_path="/api-reference/dataflow/pipeline-class.html",
                        source="/path/to/src/dataflow",
                        params={"CLASS_ID": "Pipeline"}
                    )
                ]
            )
        ]
        source_data = {
            "/path/to/src/dataflow": SourceData(
                classes=[
                    ClassData(
                        name="Pipeline",
                        short_description="A pipeline",
                        full_description="",
                        methods=[
                            FunctionData(name="run", args=[], return_type="None", short_description="Run the pipeline", full_description="", parameters=[], returns=None, raises=[])
                        ],
                        decorators=[],
                        base_classes=[],
                        properties=[]
                    )
                ],
                functions=[],
                constants=[]
            )
        }

        index = build_index(tree, source_data)

        # Should have method indexed
        assert "dataflow/Pipeline.run" in index.folder_class_index
        assert index.folder_class_index["dataflow/Pipeline.run"] == "/api-reference/dataflow/pipeline-class.html"


class TestCrossLinkPattern:
    """Test the cross-link pattern matching."""

    def test_pattern_simple(self):
        """Simple [[Target]] pattern."""
        import re
        CROSS_LINK_PATTERN = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]')

        match = CROSS_LINK_PATTERN.search("See [[Pipeline]]")
        assert match.group(1) == "Pipeline"
        assert match.group(2) is None

    def test_pattern_with_display(self):
        """[[Target|display text]] pattern."""
        import re
        CROSS_LINK_PATTERN = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]')

        match = CROSS_LINK_PATTERN.search("[[Pipeline|The Class]]")
        assert match.group(1) == "Pipeline"
        assert match.group(2) == "The Class"

    def test_pattern_with_method(self):
        """[[Target.method]] pattern."""
        import re
        CROSS_LINK_PATTERN = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]')

        match = CROSS_LINK_PATTERN.search("[[Pipeline.run]]")
        assert match.group(1) == "Pipeline.run"
        assert match.group(2) is None
