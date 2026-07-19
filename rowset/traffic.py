from __future__ import annotations

from typing import Literal

TrafficCategory = Literal[
    "api_client",
    "ai_agent",
    "link_preview",
    "crawler",
    "unknown_automation",
    "human",
]

_API_INTERFACES = frozenset({"rest", "mcp"})

# Interactive agent retrieval only. AI indexing and training bots belong to crawlers.
_AI_AGENT_TOKENS = ("chatgpt-user", "claude-user", "perplexity-user")
_LINK_PREVIEW_TOKENS = (
    "discordbot",
    "facebookexternalhit",
    "linkedinbot",
    "slackbot-linkexpanding",
    "telegrambot",
    "twitterbot",
    "whatsapp",
)
_CRAWLER_TOKENS = (
    "ahrefsbot",
    "amazonbot",
    "anthropic-ai",
    "applebot",
    "archive.org_bot",
    "baiduspider",
    "bingbot",
    "bytespider",
    "ccbot",
    "claudebot",
    "cohere-ai",
    "duckduckbot",
    "google-extended",
    "googlebot",
    "gptbot",
    "mj12bot",
    "oai-searchbot",
    "perplexitybot",
    "pingdom",
    "semrushbot",
    "statuscake",
    "uptimerobot",
    "yandexbot",
)
_GENERIC_SCRIPT_TOKENS = (
    "aiohttp",
    "axios",
    "curl/",
    "go-http-client",
    "httpx/",
    "java/",
    "libwww-perl",
    "node-fetch",
    "okhttp",
    "php/",
    "python-requests",
    "ruby/",
    "scrapy",
    "undici",
    "wget/",
)
_BROWSER_TOKENS = (
    "chrome/",
    "crios/",
    "edg/",
    "edga/",
    "edgios/",
    "firefox/",
    "fxios/",
    "opr/",
    "safari/",
)


def _contains_any(user_agent: str, tokens: tuple[str, ...]) -> bool:
    return any(token in user_agent for token in tokens)


def classify_traffic(*, request_interface: str, user_agent: str | None) -> TrafficCategory:
    """Return one bounded deterministic traffic category without retaining the user agent."""
    if request_interface.casefold() in _API_INTERFACES:
        return "api_client"

    normalized_user_agent = (user_agent or "").strip().casefold()
    if _contains_any(normalized_user_agent, _AI_AGENT_TOKENS):
        return "ai_agent"
    if _contains_any(normalized_user_agent, _LINK_PREVIEW_TOKENS):
        return "link_preview"
    if _contains_any(normalized_user_agent, _CRAWLER_TOKENS):
        return "crawler"
    if not normalized_user_agent or _contains_any(normalized_user_agent, _GENERIC_SCRIPT_TOKENS):
        return "unknown_automation"
    if "mozilla/5.0" in normalized_user_agent and _contains_any(
        normalized_user_agent,
        _BROWSER_TOKENS,
    ):
        return "human"
    return "unknown_automation"
