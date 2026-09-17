"""抓取页面 HTML。"""

from __future__ import annotations

import time

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}


class FetchError(Exception):
    def __init__(self, url: str, message: str, status: int | None = None):
        super().__init__(message)
        self.url = url
        self.status = status
        self.message = message


def normalize_url(raw: str) -> str:
    text = str(raw or "").strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return ""
    if text.startswith("//"):
        return "https:" + text
    if not text.lower().startswith(("http://", "https://")):
        text = "https://" + text.lstrip("/")
    return text


def fetch_html(url: str, timeout: int = 20, retries: int = 2) -> tuple[str, str]:
    """返回 (最终 URL, HTML)。失败抛 FetchError。"""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(
                url,
                headers=DEFAULT_HEADERS,
                timeout=timeout,
                allow_redirects=True,
            )
            final = resp.url
            if resp.status_code >= 400:
                raise FetchError(final, f"HTTP {resp.status_code}", resp.status_code)
            resp.encoding = resp.apparent_encoding or "utf-8"
            return final, resp.text
        except FetchError:
            raise
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
    raise FetchError(url, f"请求失败: {last_err}")
