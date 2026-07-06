# SPDX-FileCopyrightText: 2026 NTU AI Club
# SPDX-License-Identifier: GPL-3.0-or-later

import re


URL_PLACEHOLDER = "(連結讀取錯誤，請重新索取)"
URL_PATTERN = re.compile(r"https?://[^\s\)）\]」'>,，、。]+")


def extract_urls(text: str) -> set[str]:
    return set(URL_PATTERN.findall(text or ""))


def parse_no_response(text: str) -> tuple[bool, str | None]:
    if "NO_RESPONSE" not in text:
        return False, None
    match = re.search(r"\[NO_RESPONSE(?::(.+?))?\]", text)
    if match:
        return True, match.group(1) or None
    return True, None


def validate_urls_in_response(
    response: str,
    tool_results: list[str],
    prompt_text: str = "",
) -> str:
    allowed_urls = extract_urls(prompt_text)
    for result in tool_results:
        allowed_urls.update(extract_urls(result))

    for url in URL_PATTERN.findall(response):
        url_norm = url.rstrip("/")
        if not any(
            url_norm.startswith(allowed.rstrip("/"))
            or allowed.rstrip("/").startswith(url_norm)
            for allowed in allowed_urls
        ):
            response = response.replace(url, URL_PLACEHOLDER)

    return response
