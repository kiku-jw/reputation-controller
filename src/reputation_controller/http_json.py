"""Small stdlib JSON-over-HTTP helper."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request


class HttpJsonClient:
    def get_json(self, url: str) -> object:
        request = urllib.request.Request(
            url,
            headers={
                "accept": "application/json",
                "user-agent": "reputation-controller",
            },
        )
        response = self._open(request)
        try:
            return json.loads(response.read().decode("utf-8"))
        finally:
            response.close()

    def _open(self, request: urllib.request.Request) -> object:
        try:
            return urllib.request.urlopen(request, timeout=20)
        except urllib.error.URLError:
            context = _certifi_ssl_context()
            if context is None:
                raise
            return urllib.request.urlopen(request, timeout=20, context=context)


def _certifi_ssl_context() -> ssl.SSLContext | None:
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())
