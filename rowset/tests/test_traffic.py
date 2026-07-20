import pytest

from rowset.traffic import classify_traffic


@pytest.mark.parametrize(
    ("request_interface", "user_agent", "expected"),
    [
        ("rest", "Mozilla/5.0 Chrome/126.0.0.0 Safari/537.36", "api_client"),
        ("mcp", "ChatGPT-User/1.0", "api_client"),
        ("web", "ChatGPT-User/1.0", "ai_agent"),
        ("web", "Slackbot-LinkExpanding 1.0", "link_preview"),
        ("web", "GPTBot/1.2", "crawler"),
        ("web", "Mozilla/5.0 (Macintosh) Chrome/126.0.0.0 Safari/537.36", "human"),
        ("htmx", "Mozilla/5.0 (iPhone) Version/17.5 Mobile Safari/604.1", "human"),
        ("web", "curl/8.7.1", "unknown_automation"),
        ("web", "", "unknown_automation"),
        ("web", "bespoke-fetcher/1.0", "unknown_automation"),
    ],
)
def test_classify_traffic_uses_bounded_first_match_rules(
    request_interface,
    user_agent,
    expected,
):
    assert classify_traffic(request_interface=request_interface, user_agent=user_agent) == expected


def test_classify_traffic_matches_tokens_case_insensitively():
    assert classify_traffic(request_interface="web", user_agent="gPtBoT/1.2") == "crawler"


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [
        ("ChatGPT-User/1.0 GPTBot/1.2", "ai_agent"),
        ("Slackbot-LinkExpanding 1.0 Googlebot/2.1", "link_preview"),
        ("Mozilla/5.0 Chrome/126.0.0.0 Safari/537.36 curl/8.7.1", "unknown_automation"),
    ],
)
def test_classify_traffic_uses_first_matching_category_for_mixed_tokens(user_agent, expected):
    assert classify_traffic(request_interface="web", user_agent=user_agent) == expected
