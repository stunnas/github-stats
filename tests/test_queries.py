"""
Checks that the locked aiohttp and requests work with github_stats.py, using a
local stub server. Nothing here talks to GitHub or needs a token.
"""

import contextlib
import io
import json
import ssl
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import aiohttp
import certifi
import requests

import generate_images  # noqa: F401 (the workflow's entry point has to import)
import github_stats

GITHUB = "https://api.github.com"
TOKEN = "stub-token"
GRAPHQL_RESULT = {"data": {"viewer": {"login": "stub"}}}
REST_RESULT = [{"total": 3}]


class StubGitHub(BaseHTTPRequestHandler):
    def _send(self, status, body=None):
        data = b"" if body is None else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.server.auth.append(self.headers["Authorization"])
        self._send(200, GRAPHQL_RESULT)

    def do_GET(self):
        self.server.auth.append(self.headers["Authorization"])
        if self.path.startswith("/computing") and not self.server.computed:
            self.server.computed = True
            self._send(202)
        else:
            self._send(200, REST_RESULT)

    def log_message(self, format, *args):
        pass


class LocalSession:
    """Sends a real aiohttp request to the stub, not to api.github.com."""

    def __init__(self, session, base):
        self.session = session
        self.base = base

    def post(self, url, **kwargs):
        return self.session.post(url.replace(GITHUB, self.base), **kwargs)

    def get(self, url, **kwargs):
        return self.session.get(url.replace(GITHUB, self.base), **kwargs)


class BrokenSession:
    """Stands in for an aiohttp that fails, to force the requests fallback."""

    def post(self, url, **kwargs):
        raise aiohttp.ClientError("broken on purpose")

    def get(self, url, **kwargs):
        raise aiohttp.ClientError("broken on purpose")


class QueriesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), StubGitHub)
        self.server.auth = []
        self.server.computed = False
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        real_post, real_get = requests.post, requests.get
        self.requests_post = self._patch_requests("post", real_post)
        self.requests_get = self._patch_requests("get", real_get)

    def _patch_requests(self, name, real):
        def local(url, **kwargs):
            return real(url.replace(GITHUB, self.base), timeout=5, **kwargs)

        patcher = mock.patch.object(requests, name, side_effect=local)
        self.addCleanup(patcher.stop)
        return patcher.start()

    async def _run(self, session, call):
        queries = github_stats.Queries("stub", TOKEN, session)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = await call(queries)
        return result, output.getvalue()

    async def _run_aiohttp(self, call):
        async with aiohttp.ClientSession() as session:
            return await self._run(LocalSession(session, self.base), call)

    async def test_graphql_through_aiohttp(self):
        result, output = await self._run_aiohttp(lambda q: q.query("{ viewer }"))
        self.assertEqual(result, GRAPHQL_RESULT)
        self.assertNotIn("aiohttp failed", output)
        self.requests_post.assert_not_called()
        self.assertEqual(self.server.auth, [f"Bearer {TOKEN}"])

    async def test_rest_through_aiohttp(self):
        result, output = await self._run_aiohttp(lambda q: q.query_rest("/stats"))
        self.assertEqual(result, REST_RESULT)
        self.assertNotIn("aiohttp failed", output)
        self.requests_get.assert_not_called()
        self.assertEqual(self.server.auth, [f"token {TOKEN}"])

    async def test_rest_retries_after_202(self):
        with mock.patch.object(github_stats.asyncio, "sleep", mock.AsyncMock()):
            result, output = await self._run_aiohttp(
                lambda q: q.query_rest("/computing")
            )
        self.assertEqual(result, REST_RESULT)
        self.assertIn("A path returned 202", output)
        self.assertEqual(len(self.server.auth), 2)

    async def test_graphql_falls_back_to_requests(self):
        result, output = await self._run(
            BrokenSession(), lambda q: q.query("{ viewer }")
        )
        self.assertEqual(result, GRAPHQL_RESULT)
        self.assertIn("aiohttp failed for GraphQL query", output)
        self.requests_post.assert_called_once()

    async def test_rest_falls_back_to_requests(self):
        result, output = await self._run(
            BrokenSession(), lambda q: q.query_rest("/stats")
        )
        self.assertEqual(result, REST_RESULT)
        self.assertIn("aiohttp failed for rest query", output)
        self.requests_get.assert_called_once()


class CertificatesTest(unittest.TestCase):
    def test_certifi_bundle_loads(self):
        context = ssl.create_default_context(cafile=certifi.where())
        self.assertGreater(len(context.get_ca_certs()), 0)


if __name__ == "__main__":
    unittest.main()
