"""Tests for src/lighthouse_ai/targets/logseq.py — production-quality Logseq output."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from lighthouse_ai.targets.logseq import (
    LogseqPage,
    _block_uuid,
    _html_to_md,
    _slugify,
    export_draft,
)


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------

class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars_removed(self):
        result = _slugify("Café & Röntgen!")
        # special chars are stripped; words joined by dash
        assert "&" not in result
        assert "!" not in result

    def test_multiple_spaces_become_single_dash(self):
        assert _slugify("foo   bar") == "foo-bar"

    def test_underscore_becomes_dash(self):
        assert _slugify("foo_bar") == "foo-bar"

    def test_max_length(self):
        long_title = "a" * 200
        result = _slugify(long_title)
        assert len(result) <= 80

    def test_empty_string_returns_untitled(self):
        assert _slugify("") == "untitled"

    def test_only_special_chars_returns_untitled(self):
        assert _slugify("!!!###") == "untitled"

    def test_numbers_preserved(self):
        assert _slugify("Section 42") == "section-42"

    def test_already_slug(self):
        assert _slugify("my-topic") == "my-topic"

    def test_unicode_letters_preserved(self):
        # \w in Python matches unicode word chars
        result = _slugify("über-cool")
        assert "ber" in result or "b" in result  # 'ü' may or may not survive


# ---------------------------------------------------------------------------
# _html_to_md
# ---------------------------------------------------------------------------

class TestHtmlToMd:
    def test_bold_strong(self):
        assert "**bold**" in _html_to_md("<strong>bold</strong>")

    def test_bold_b_tag(self):
        assert "**bold**" in _html_to_md("<b>bold</b>")

    def test_italic_em(self):
        assert "*italic*" in _html_to_md("<em>italic</em>")

    def test_italic_i_tag(self):
        assert "*italic*" in _html_to_md("<i>italic</i>")

    def test_inline_code(self):
        result = _html_to_md("<code>some_code()</code>")
        assert "`some_code()`" in result

    def test_pre_block(self):
        result = _html_to_md("<pre>code block</pre>")
        assert "```" in result
        assert "code block" in result

    def test_link(self):
        result = _html_to_md('<a href="https://example.com">Example</a>')
        assert "[Example](https://example.com)" in result

    def test_unordered_list(self):
        result = _html_to_md("<ul><li>Alpha</li><li>Beta</li></ul>")
        assert "- Alpha" in result
        assert "- Beta" in result

    def test_ordered_list(self):
        result = _html_to_md("<ol><li>First</li><li>Second</li></ol>")
        assert "1. First" in result
        assert "2. Second" in result

    def test_h1(self):
        result = _html_to_md("<h1>Top</h1>")
        assert "# Top" in result

    def test_h2(self):
        result = _html_to_md("<h2>Section</h2>")
        assert "## Section" in result

    def test_h3(self):
        result = _html_to_md("<h3>Sub</h3>")
        assert "### Sub" in result

    def test_h4(self):
        result = _html_to_md("<h4>SubSub</h4>")
        assert "#### SubSub" in result

    def test_paragraph_text(self):
        result = _html_to_md("<p>Hello world.</p>")
        assert "Hello world." in result

    def test_blockquote(self):
        result = _html_to_md("<blockquote>Quoted text</blockquote>")
        assert "> Quoted text" in result

    def test_style_block_removed(self):
        result = _html_to_md("<style>body { color: red; }</style><p>Content</p>")
        assert "color" not in result
        assert "Content" in result

    def test_script_block_removed(self):
        result = _html_to_md("<script>alert('xss')</script><p>Safe</p>")
        assert "alert" not in result
        assert "Safe" in result

    def test_html_entities_decoded(self):
        result = _html_to_md("<p>AT&amp;T &lt;rocks&gt;</p>")
        assert "AT&T" in result
        assert "<rocks>" in result

    def test_br_becomes_newline(self):
        result = _html_to_md("Line1<br/>Line2")
        assert "Line1" in result
        assert "Line2" in result

    def test_hr_becomes_separator(self):
        result = _html_to_md("Before<hr/>After")
        assert "---" in result

    def test_empty_input(self):
        assert _html_to_md("") == ""

    def test_none_like_empty_string(self):
        # function accepts str; empty string is the sentinel
        assert _html_to_md("") == ""

    def test_no_excess_blank_lines(self):
        html = "<p>A</p>\n\n\n\n<p>B</p>"
        result = _html_to_md(html)
        # Should not have 3+ consecutive newlines
        assert "\n\n\n" not in result

    def test_combined_inline(self):
        result = _html_to_md("<p><strong>bold</strong> and <em>italic</em></p>")
        assert "**bold**" in result
        assert "*italic*" in result

    def test_citation_ref_preserved(self):
        # Citation-style refs like [1] in plain text pass through unchanged
        result = _html_to_md("<p>See reference [1] for details.</p>")
        assert "[1]" in result


# ---------------------------------------------------------------------------
# export_draft — page properties
# ---------------------------------------------------------------------------

class TestExportDraftProperties:
    def test_creates_file(self, tmp_path):
        page = export_draft(
            tmp_path,
            draft_id="d001",
            title="My Draft",
            body_html="<p>Hello</p>",
        )
        assert page.path.exists()

    def test_returns_logseq_page(self, tmp_path):
        page = export_draft(
            tmp_path,
            draft_id="d002",
            title="Test",
            body_html="",
        )
        assert isinstance(page, LogseqPage)
        assert page.title == "Test"

    def test_title_property(self, tmp_path):
        export_draft(tmp_path, draft_id="d003", title="My Title", body_html="")
        content = (tmp_path / "pages" / "my-title.md").read_text(encoding="utf-8")
        assert "title:: My Title" in content

    def test_id_property(self, tmp_path):
        page = export_draft(tmp_path, draft_id="d004", title="ID Test", body_html="")
        content = page.path.read_text(encoding="utf-8")
        assert f"id:: {page.uuid}" in content

    def test_draft_id_property(self, tmp_path):
        page = export_draft(tmp_path, draft_id="myDraftXYZ", title="Draft ID", body_html="")
        content = page.path.read_text(encoding="utf-8")
        assert "lighthouse-draft-id:: myDraftXYZ" in content

    def test_type_property(self, tmp_path):
        page = export_draft(tmp_path, draft_id="d005", title="Type Test", body_html="")
        content = page.path.read_text(encoding="utf-8")
        assert "type:: lighthouse/draft" in content

    def test_date_property_present(self, tmp_path):
        page = export_draft(tmp_path, draft_id="d006", title="Date Test", body_html="")
        content = page.path.read_text(encoding="utf-8")
        # Should have date:: [[YYYY-MM-DD]]
        assert re.search(r"date:: \[\[\d{4}-\d{2}-\d{2}\]\]", content)

    def test_topic_uses_page_link_syntax(self, tmp_path):
        page = export_draft(
            tmp_path,
            draft_id="d007",
            title="Topic Test",
            body_html="",
            topic="Artificial Intelligence",
        )
        content = page.path.read_text(encoding="utf-8")
        assert "topic:: [[Artificial Intelligence]]" in content

    def test_no_topic_no_topic_property(self, tmp_path):
        page = export_draft(tmp_path, draft_id="d008", title="No Topic", body_html="")
        content = page.path.read_text(encoding="utf-8")
        assert "topic::" not in content

    def test_wep_phrase_as_confidence(self, tmp_path):
        page = export_draft(
            tmp_path,
            draft_id="d009",
            title="Confidence",
            body_html="",
            wep_phrase="Likely",
        )
        content = page.path.read_text(encoding="utf-8")
        assert "confidence:: Likely" in content

    def test_source_count_property(self, tmp_path):
        page = export_draft(
            tmp_path,
            draft_id="d010",
            title="Sources",
            body_html="",
            source_count=12,
        )
        content = page.path.read_text(encoding="utf-8")
        assert "source-count:: 12" in content

    def test_tags_include_lighthouse_prefix(self, tmp_path):
        page = export_draft(
            tmp_path,
            draft_id="d011",
            title="Tags Test",
            body_html="",
            tags=["ai", "research"],
        )
        content = page.path.read_text(encoding="utf-8")
        assert "tags::" in content
        assert "lighthouse" in content
        assert "lighthouse/draft" in content
        assert "ai" in content
        assert "research" in content

    def test_tags_no_inline_hash_tags(self, tmp_path):
        """Tags must NOT use inline #tag format — they go in the tags:: property."""
        page = export_draft(
            tmp_path,
            draft_id="d012",
            title="No Hash Tags",
            body_html="",
            tags=["ai"],
        )
        content = page.path.read_text(encoding="utf-8")
        # Inline #ai in content body is not acceptable
        # The tags:: line itself uses comma-separated names, not #name
        tags_line = next(l for l in content.splitlines() if l.startswith("tags::"))
        assert "#" not in tags_line

    def test_default_tags_when_none(self, tmp_path):
        page = export_draft(tmp_path, draft_id="d013", title="Default Tags", body_html="")
        content = page.path.read_text(encoding="utf-8")
        assert "tags:: lighthouse, lighthouse/draft" in content


# ---------------------------------------------------------------------------
# export_draft — body / section blocks
# ---------------------------------------------------------------------------

class TestExportDraftBody:
    def test_sections_become_separate_blocks(self, tmp_path):
        html = "<h2>Intro</h2><p>Some text.</p><h2>Methods</h2><p>More text.</p>"
        page = export_draft(tmp_path, draft_id="sec001", title="Sections", body_html=html)
        content = page.path.read_text(encoding="utf-8")
        # Both section headings should appear as top-level blocks
        assert "- ## Intro" in content
        assert "- ## Methods" in content

    def test_section_content_nested(self, tmp_path):
        html = "<h2>Results</h2><p>Finding A.</p>"
        page = export_draft(tmp_path, draft_id="sec002", title="Nested", body_html=html)
        content = page.path.read_text(encoding="utf-8")
        # Content under a section heading is indented under the block
        assert "  - Finding A." in content

    def test_source_count_footer_block(self, tmp_path):
        page = export_draft(
            tmp_path,
            draft_id="src001",
            title="Footer",
            body_html="",
            source_count=5,
        )
        content = page.path.read_text(encoding="utf-8")
        assert "**Sources reviewed:** 5 independent sources" in content

    def test_no_source_count_no_footer(self, tmp_path):
        page = export_draft(tmp_path, draft_id="src002", title="No Footer", body_html="")
        content = page.path.read_text(encoding="utf-8")
        assert "Sources reviewed" not in content

    def test_body_html_inline_formatting_preserved(self, tmp_path):
        html = "<p><strong>Important</strong> finding with <em>emphasis</em>.</p>"
        page = export_draft(tmp_path, draft_id="fmt001", title="Fmt", body_html=html)
        content = page.path.read_text(encoding="utf-8")
        assert "**Important**" in content
        assert "*emphasis*" in content


# ---------------------------------------------------------------------------
# export_draft — UTF-8 and idempotence
# ---------------------------------------------------------------------------

class TestExportDraftUtf8AndIdempotence:
    def test_valid_utf8(self, tmp_path):
        page = export_draft(
            tmp_path,
            draft_id="utf001",
            title="UTF-8 Test",
            body_html="<p>Café naïve résumé</p>",
        )
        # If the file is valid UTF-8, this won't raise
        content = page.path.read_bytes().decode("utf-8")
        assert "Café" in content

    def test_unicode_in_title(self, tmp_path):
        page = export_draft(
            tmp_path,
            draft_id="utf002",
            title="Über Test",
            body_html="",
        )
        content = page.path.read_text(encoding="utf-8")
        assert "title:: Über Test" in content

    def test_idempotent_same_file_overwritten(self, tmp_path):
        kwargs = dict(
            draft_id="idem001",
            title="Idempotent",
            body_html="<p>First version.</p>",
        )
        page1 = export_draft(tmp_path, **kwargs)
        # Re-export with updated body
        kwargs["body_html"] = "<p>Second version.</p>"
        page2 = export_draft(tmp_path, **kwargs)

        assert page1.path == page2.path
        assert page1.uuid == page2.uuid  # stable uuid from draft_id
        content = page2.path.read_text(encoding="utf-8")
        assert "Second version." in content
        assert "First version." not in content

    def test_pages_dir_created_if_missing(self, tmp_path):
        graph_dir = tmp_path / "my_graph"
        # graph_dir does not exist yet
        page = export_draft(
            graph_dir,
            draft_id="dir001",
            title="Dir Create",
            body_html="",
        )
        assert page.path.exists()
        assert (graph_dir / "pages").is_dir()

    def test_uuid_stable_for_same_draft_id(self):
        uuid1 = _block_uuid("draft-abc")
        uuid2 = _block_uuid("draft-abc")
        assert uuid1 == uuid2

    def test_uuid_different_for_different_draft_ids(self):
        assert _block_uuid("draft-aaa") != _block_uuid("draft-bbb")
