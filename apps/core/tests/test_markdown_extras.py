from apps.core.templatetags.markdown_extras import markdown


def test_markdown_filter_sanitizes_html_and_unsafe_links():
    rendered = markdown(
        "**Safe** <script>alert('x')</script> "
        "[bad](javascript:alert(1)) [good](https://example.com)"
    )

    assert "<strong>Safe</strong>" in rendered
    assert "<script" not in rendered
    assert "javascript:" not in rendered
    assert 'href="https://example.com"' in rendered
