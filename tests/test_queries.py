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
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.calls.append(("POST", self.path, body))
        self.server.auth.append(self.headers["Authorization"])
        self._send(200, GRAPHQL_RESULT)

    def do_GET(self):
        self.server.calls.append(("GET", self.path, None))
        self.server.auth.append(self.headers["Authorization"])
        if self.path == "/computing" and not self.server.computed:
            self.server.computed = True
            self._send(202)
        elif self.path == "/always-computing":
            self._send(202)
        elif self.path == "/html-error" and "aiohttp" in self.headers["User-Agent"]:
            self._send_html_error()
        else:
            self._send(200, REST_RESULT)

    def _send_html_error(self):
        data = b"<html>Server error</html>"
        self.send_response(500)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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
        self.server.calls = []
        self.server.computed = False
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        thread = threading.Thread(
            target=self.server.serve_forever, args=(0.01,), daemon=True
        )
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        real_post, real_get = requests.post, requests.get
        self.requests_post = self._patch_requests("post", real_post)
        self.requests_get = self._patch_requests("get", real_get)

    def _patch_requests(self, name, real):
        def local(url, **kwargs):
            kwargs.setdefault("timeout", 5)
            return real(url.replace(GITHUB, self.base), **kwargs)

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
        self.assertEqual(
            self.server.calls, [("POST", "/graphql", {"query": "{ viewer }"})]
        )

    async def test_rest_through_aiohttp(self):
        result, output = await self._run_aiohttp(lambda q: q.query_rest("/stats"))
        self.assertEqual(result, REST_RESULT)
        self.assertNotIn("aiohttp failed", output)
        self.requests_get.assert_not_called()
        self.assertEqual(self.server.auth, [f"token {TOKEN}"])
        self.assertEqual(self.server.calls, [("GET", "/stats", None)])

    async def _query_rest_without_waiting(self, path):
        sleep = mock.AsyncMock()

        async def call(queries):
            with mock.patch("asyncio.sleep", sleep):
                return await queries.query_rest(path)

        result, output = await self._run_aiohttp(call)
        return result, output, sleep

    async def test_rest_retries_after_202(self):
        result, output, sleep = await self._query_rest_without_waiting("/computing")
        self.assertEqual(result, REST_RESULT)
        self.assertIn("A path returned 202", output)
        self.assertNotIn("aiohttp failed", output)
        self.requests_get.assert_not_called()
        sleep.assert_awaited_once_with(2)
        self.assertEqual(len(self.server.calls), 2)

    async def test_rest_gives_up_after_too_many_202s(self):
        result, output, sleep = await self._query_rest_without_waiting(
            "/always-computing"
        )
        self.assertEqual(result, {})
        self.assertIn("There were too many 202s", output)
        self.assertEqual(len(self.server.calls), 60)
        self.assertEqual(sleep.await_count, 60)

    async def test_html_error_falls_back_to_requests(self):
        result, output = await self._run_aiohttp(lambda q: q.query_rest("/html-error"))
        self.assertEqual(result, REST_RESULT)
        self.assertIn("aiohttp failed for rest query", output)
        self.requests_get.assert_called_once()

    async def test_graphql_falls_back_to_requests(self):
        result, output = await self._run(
            BrokenSession(), lambda q: q.query("{ viewer }")
        )
        self.assertEqual(result, GRAPHQL_RESULT)
        self.assertIn("aiohttp failed for GraphQL query", output)
        self.requests_post.assert_called_once()
        self.assertEqual(self.server.auth, [f"Bearer {TOKEN}"])
        self.assertEqual(
            self.server.calls, [("POST", "/graphql", {"query": "{ viewer }"})]
        )

    async def test_rest_falls_back_to_requests(self):
        result, output = await self._run(
            BrokenSession(), lambda q: q.query_rest("/stats")
        )
        self.assertEqual(result, REST_RESULT)
        self.assertIn("aiohttp failed for rest query", output)
        self.requests_get.assert_called_once()
        self.assertEqual(self.server.auth, [f"token {TOKEN}"])
        self.assertEqual(self.server.calls, [("GET", "/stats", None)])


class CertificatesTest(unittest.TestCase):
    def test_requests_ca_bundle_loads(self):
        context = ssl.create_default_context(cafile=requests.certs.where())
        self.assertGreater(len(context.get_ca_certs()), 0)
