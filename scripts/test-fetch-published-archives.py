#!/usr/bin/env python3
"""scripts/test-fetch-published-archives.py - fetch-published-archives.py against
a local HTTP server that fails on demand. No sleeping: the retry delay function is
injected, and the CLI test uses a tiny base delay through the default path only
for requests that succeed first time."""
import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "fetch-published-archives.py"
spec = importlib.util.spec_from_file_location("fetch_published_archives", SCRIPT)
fpa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fpa)

# talk to 127.0.0.1 directly, whatever proxy the machine has configured
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"


class Server:
    """Serves {path: bytes}; script[path] is a list of statuses to answer first
    (an int, or (int, retry_after))."""

    def __init__(self, files, script=None):
        self.files = files
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.hits = {}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits[self.path] = outer.hits.get(self.path, 0) + 1
                queue = outer.script.get(self.path)
                if queue:
                    status = queue.pop(0)
                    retry_after = None
                    if isinstance(status, tuple):
                        status, retry_after = status
                    self.send_response(status)
                    if retry_after is not None:
                        self.send_header("Retry-After", str(retry_after))
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = outer.files.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def sha(b):
    return hashlib.sha256(b).hexdigest()


class Download(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.sleeps = []
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            s.close()
        self.tmp.cleanup()

    def server(self, *a, **kw):
        s = Server(*a, **kw)
        self.servers.append(s)
        return s

    def fetch(self, url, name="a-1-1.nawa.tar.zst", **kw):
        return fpa.download(url, self.d / name, sleep=self.sleeps.append, **kw)

    def test_downloads_and_hashes_atomically(self):
        s = self.server({"/f": b"payload"})
        digest = self.fetch(s.url + "/f")
        self.assertEqual(digest, sha(b"payload"))
        self.assertEqual((self.d / "a-1-1.nawa.tar.zst").read_bytes(), b"payload")
        self.assertEqual(sorted(p.name for p in self.d.iterdir()), ["a-1-1.nawa.tar.zst"])
        self.assertEqual(self.sleeps, [])

    def test_retries_5xx_with_growing_backoff_then_succeeds(self):
        s = self.server({"/f": b"ok"}, {"/f": [504, 504, 502]})
        self.fetch(s.url + "/f", base=4.0, cap=100.0)
        self.assertEqual(s.hits["/f"], 4)
        self.assertEqual(len(self.sleeps), 3)
        # jitter keeps each delay in [0.5, 1.0] of 4 * 2**(n-1), and it grows
        for n, delay in enumerate(self.sleeps, 1):
            self.assertTrue(2.0 * 2 ** (n - 1) <= delay <= 4.0 * 2 ** (n - 1), (n, delay))

    def test_retry_after_is_honoured(self):
        s = self.server({"/f": b"ok"}, {"/f": [(503, 90)]})
        self.fetch(s.url + "/f", base=1.0, cap=120.0)
        self.assertEqual(len(self.sleeps), 1)
        self.assertGreaterEqual(self.sleeps[0], 90)

    def test_retry_after_is_capped(self):
        s = self.server({"/f": b"ok"}, {"/f": [(429, 99999)]})
        self.fetch(s.url + "/f", base=1.0, cap=30.0)
        self.assertLessEqual(self.sleeps[0], 30.0)

    def test_client_errors_are_not_retried(self):
        s = self.server({})
        with self.assertRaises(fpa.FetchError) as cm:
            self.fetch(s.url + "/missing")
        self.assertIn("HTTP 404", str(cm.exception))
        self.assertEqual(s.hits["/missing"], 1)
        self.assertEqual(self.sleeps, [])

    def test_gives_up_after_the_attempt_limit_and_names_the_asset(self):
        s = self.server({"/f": b"ok"}, {"/f": [504] * 10})
        with self.assertRaises(fpa.FetchError) as cm:
            self.fetch(s.url + "/f", attempts=3)
        self.assertIn("a-1-1.nawa.tar.zst", str(cm.exception))
        self.assertIn("gave up after 3 attempt(s)", str(cm.exception))
        self.assertIn("HTTP 504", str(cm.exception))
        self.assertEqual(s.hits["/f"], 3)
        self.assertFalse((self.d / "a-1-1.nawa.tar.zst").exists())
        self.assertEqual(list(self.d.iterdir()), [])

    def test_empty_body_is_rejected(self):
        s = self.server({"/f": b""})
        with self.assertRaises(fpa.FetchError) as cm:
            self.fetch(s.url + "/f")
        self.assertIn("empty", str(cm.exception))
        self.assertEqual(list(self.d.iterdir()), [])

    def test_index_mismatch_is_retried_once_then_fails_and_keeps_nothing(self):
        s = self.server({"/f": b"payload"})
        with self.assertRaises(fpa.FetchError) as cm:
            self.fetch(s.url + "/f", expect_sha256=sha(b"other"))
        self.assertIn("sha256 differs", str(cm.exception))
        self.assertEqual(s.hits["/f"], 2)
        self.assertEqual(list(self.d.iterdir()), [])

    def test_size_check(self):
        s = self.server({"/f": b"payload"})
        with self.assertRaises(fpa.FetchError) as cm:
            self.fetch(s.url + "/f", expect_size=3)
        self.assertIn("size 7", str(cm.exception))

    def test_matching_index_values_pass(self):
        s = self.server({"/f": b"payload"})
        self.fetch(s.url + "/f", expect_sha256=sha(b"payload"), expect_size=7)


class Manifest(unittest.TestCase):
    def read(self, text):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "m.tsv"
            p.write_text(text)
            return fpa.read_manifest(p)

    def test_valid_manifest(self):
        self.assertEqual(self.read("packages-0001\ta-1-1.nawa.tar.zst\nstable\tb-2-1.nawa.tar.zst\n\n"),
                         [("packages-0001", "a-1-1.nawa.tar.zst"), ("stable", "b-2-1.nawa.tar.zst")])

    def test_rejects_unsafe_lines(self):
        for bad in ("packages-0001\t../x.nawa.tar.zst\n", "packages-0001\ta.zip\n",
                    "a b\tx-1-1.nawa.tar.zst\n", "only-one-column\n",
                    "stable\ta-1-1.nawa.tar.zst\nstable\ta-1-1.nawa.tar.zst\n"):
            with self.subTest(bad):
                with self.assertRaises(fpa.FetchError):
                    self.read(bad)


class FetchAll(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.files = {
            "/o/r/releases/download/packages-0001/a-1-1.nawa.tar.zst": b"aaa",
            "/o/r/releases/download/stable/b-1-1.nawa.tar.zst": b"bbbb",
        }
        self.srv = Server(self.files)
        (self.d / "m.tsv").write_text("packages-0001\ta-1-1.nawa.tar.zst\nstable\tb-1-1.nawa.tar.zst\n")

    def tearDown(self):
        self.srv.close()
        self.tmp.cleanup()

    def run_cli(self, *extra):
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--list", str(self.d / "m.tsv"), "--repo", "o/r",
             "--out", str(self.d / "out"), "--base-url", self.srv.url, *extra],
            capture_output=True, text=True, env=dict(os.environ))

    def test_cli_downloads_everything_and_is_idempotent(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("2 downloaded, 0 already present, 0 failed", r.stdout)
        self.assertEqual((self.d / "out" / "b-1-1.nawa.tar.zst").read_bytes(), b"bbbb")
        r = self.run_cli()
        self.assertEqual(r.returncode, 0)
        self.assertIn("0 downloaded, 2 already present", r.stdout)

    def test_cli_verifies_archives_against_the_index(self):
        good = {"a-1-1.nawa.tar.zst": (sha(b"aaa"), 3), "b-1-1.nawa.tar.zst": (sha(b"bbbb"), 4)}
        index = self.d / "index.toml"
        index.write_text("".join(
            f'[[package]]\nfile = "{f}"\nsha256 = "{h}"\nsize = {n}\n' for f, (h, n) in good.items()))
        self.assertEqual(self.run_cli("--index", str(index)).returncode, 0)

        (self.d / "out" / "b-1-1.nawa.tar.zst").unlink()
        index.write_text(index.read_text().replace(sha(b"bbbb"), "0" * 64))
        r = self.run_cli("--index", str(index))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("FAILED b-1-1.nawa.tar.zst: sha256 differs from the index", r.stderr)
        self.assertFalse((self.d / "out" / "b-1-1.nawa.tar.zst").exists())

    def test_cli_reports_every_failure_and_still_fetches_the_rest(self):
        del self.srv.files["/o/r/releases/download/stable/b-1-1.nawa.tar.zst"]
        r = self.run_cli()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("1 downloaded, 0 already present, 1 failed", r.stdout)
        self.assertIn("FAILED b-1-1.nawa.tar.zst: HTTP 404", r.stderr)
        self.assertTrue((self.d / "out" / "a-1-1.nawa.tar.zst").exists())

    def test_cli_caps_jobs_and_validates_arguments(self):
        r = self.run_cli("--jobs", "32")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Capping --jobs from 32 to 4", r.stderr)
        bad = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--list", str(self.d / "m.tsv"), "--repo", "not a repo",
             "--out", str(self.d / "o2")], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        remote = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--list", str(self.d / "m.tsv"), "--repo", "o/r",
             "--out", str(self.d / "o3"), "--base-url", "http://example.com"], capture_output=True, text=True)
        self.assertEqual(remote.returncode, 2)


class Backoff(unittest.TestCase):
    def test_delay_growth_cap_and_retry_after(self):
        class Fixed:
            @staticmethod
            def uniform(a, b):
                return 1.0
        d = lambda n, ra=None: fpa.backoff_delay(n, 5.0, 120.0, ra, Fixed)
        self.assertEqual([d(1), d(2), d(3), d(4), d(5)], [5.0, 10.0, 20.0, 40.0, 80.0])
        self.assertEqual(d(6), 120.0)
        self.assertEqual(d(1, 60.0), 60.0)
        self.assertEqual(d(1, 1.0), 5.0)
        self.assertEqual(d(1, 10_000.0), 120.0)

    def test_retry_after_parsing(self):
        self.assertEqual(fpa.parse_retry_after("17"), 17.0)
        self.assertIsNone(fpa.parse_retry_after(None))
        self.assertIsNone(fpa.parse_retry_after("soon"))
        self.assertGreaterEqual(fpa.parse_retry_after("Wed, 21 Oct 2037 07:28:00 GMT"), 0.0)


if __name__ == "__main__":
    unittest.main()
