"""End-to-end tests for the Confluence CLI (tools/confluence_page.py).

Each test runs the real CLI in a subprocess against an in-process fake
Confluence Server REST API, so the whole chain is exercised:

    confluence_page.py --> ConfluenceManager --> atlassian-python-api
          (argv, env)        (tuple contract)      (real HTTP requests)
                                                          |
                                                          v
                                          FakeConfluence (ThreadingHTTPServer)
                                          pages dict + request log

The fake server keeps page state and enforces the same optimistic-locking
rule as Confluence (a PUT must carry version = current + 1), so version
handling, body preservation and width preservation are checked against the
requests that actually go over the wire.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CLI = Path(__file__).resolve().parent.parent / "tools" / "confluence_page.py"
GOOD_TOKEN = "good-token"

STORAGE_BODY = (
    "<h1>Runbook</h1><p>Restart the <strong>worker</strong>.</p>"
    '<ac:structured-macro ac:name="code"><ac:plain-text-body>'
    "<![CDATA[kubectl rollout restart deploy/worker]]>"
    "</ac:plain-text-body></ac:structured-macro>"
)


class FakeConfluence:
    """Stateful subset of the Confluence Server REST API"""

    def __init__(self):
        self.pages: dict[str, dict] = {}
        self.requests: list[tuple[str, str, dict | None]] = []
        self.next_id = 1000
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def _send(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                fake.requests.append((self.command, self.path, body))
                status, payload = fake.route(
                    self.command, self.path, body, self.headers.get("Authorization")
                )
                self._send(status, payload)

            do_GET = do_POST = do_PUT = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def add_page(self, title, body, space="DOC", parent=None, full_width=False):
        page_id = str(self.next_id)
        self.next_id += 1
        self.pages[page_id] = {
            "id": page_id,
            "title": title,
            "space": space,
            "body": body,
            "version": 1,
            "parent": parent,
            # None = no content-appearance property, the usual state on Data Center
            "width": "full-width" if full_width else None,
        }
        return page_id

    def render(self, page, expand=None):
        """Render a page like Confluence: optional parts appear only when expanded.

        expand=None means "everything" (POST/PUT responses); otherwise it is the
        raw comma-separated expand parameter, e.g. "space,version,body.storage".
        """
        ancestors = [{"id": page["parent"], "type": "page"}] if page["parent"] else []
        optional = {
            "space": {"key": page["space"]},
            "version": {
                "number": page["version"],
                "when": "2026-11-19T10:00:00.000Z",
                "by": {"displayName": "Tester"},
            },
            "ancestors": ancestors,
            "body": {"storage": {"value": page["body"], "representation": "storage"}},
            "metadata": {
                "properties": {
                    k: {"value": v}
                    for k, v in [("content-appearance-published", page["width"])]
                    if v is not None
                }
            },
        }
        rendered = {
            "id": page["id"],
            "type": "page",
            "title": page["title"],
            "_links": {"webui": f"/pages/viewpage.action?pageId={page['id']}"},
        }
        wanted = (
            None
            if expand is None
            else {e.split(".")[0] for e in expand.split(",") if e}
        )
        for key, value in optional.items():
            if wanted is None or key in wanted:
                rendered[key] = value
        return rendered

    def route(self, method, raw_path, body, auth):
        url = urlparse(raw_path)
        query = parse_qs(url.query)
        expand = query.get("expand", [""])[0]
        parts = url.path.strip("/").split("/")  # rest, api, ...
        if parts[:2] != ["rest", "api"]:
            return 404, {"message": "not found"}
        parts = parts[2:]

        if parts == ["user", "current"]:
            if auth == f"Bearer {GOOD_TOKEN}":
                return 200, {"type": "known", "username": "tester"}
            return 200, {"type": "anonymous"}

        if parts == ["search"] and method == "GET":
            needle = query["cql"][0].split('"')[1] if '"' in query["cql"][0] else ""
            hits = [
                p
                for p in self.pages.values()
                if needle in p["body"] or needle in p["title"]
            ]
            limit = int(query.get("limit", ["25"])[0])
            content_expand = ",".join(
                e.removeprefix("content.") for e in expand.split(",") if e
            )
            results = [
                {
                    "content": self.render(p, content_expand),
                    "excerpt": f"...@@@hl@@@{needle}@@@endhl@@@...",
                }
                for p in hits
            ]
            return 200, {"results": results[:limit], "totalSize": len(results)}

        if parts == ["content"] and method == "GET":
            hits = [
                self.render(p, expand)
                for p in self.pages.values()
                if p["space"] == query["spaceKey"][0]
                and p["title"] == query["title"][0]
            ]
            return 200, {"results": hits, "size": len(hits)}

        if parts == ["content"] and method == "POST":
            ancestors = body.get("ancestors") or []
            page_id = self.add_page(
                body["title"],
                body["body"]["storage"]["value"],
                space=body["space"]["key"],
                parent=ancestors[0]["id"] if ancestors else None,
            )
            return 200, self.render(self.pages[page_id])

        if parts and parts[0] == "content" and len(parts) >= 2:
            page = self.pages.get(parts[1])
            if page is None:
                return 404, {"statusCode": 404, "message": "No content found with id"}
            rest = parts[2:]
            # Data Center 8.5 answers 500 when expand names a missing property
            for e in expand.split(","):
                if e.startswith("metadata.properties."):
                    key = e.removeprefix("metadata.properties.")
                    if key != "content-appearance-published" or page["width"] is None:
                        return 500, {
                            "statusCode": 500,
                            "message": "Internal Server Error",
                        }
            if rest[:1] == ["property"] and len(rest) == 2 and method == "GET":
                if rest[1] == "content-appearance-published" and page["width"]:
                    return 200, {"key": rest[1], "value": page["width"]}
                return 404, {
                    "statusCode": 404,
                    "message": f"No content property found with key: {rest[1]}",
                }
            if rest == [] and method == "GET":
                return 200, self.render(page, expand)
            if rest == ["history"]:
                return 200, {"lastUpdated": {"number": page["version"]}}
            if rest == ["child", "page"]:
                children = [
                    self.render(p, expand)
                    for p in self.pages.values()
                    if p["parent"] == page["id"]
                ]
                return 200, {"results": children, "size": len(children)}
            if rest == [] and method == "PUT":
                if body["version"]["number"] != page["version"] + 1:
                    return 409, {
                        "statusCode": 409,
                        "message": "Version must be incremented on update",
                    }
                page["version"] += 1
                page["title"] = body["title"]
                # Pessimistic: treat a PUT without a body as clearing the page
                page["body"] = body.get("body", {}).get("storage", {}).get("value", "")
                props = body.get("metadata", {}).get("properties", {})
                if "content-appearance-published" in props:
                    page["width"] = props["content-appearance-published"]["value"]
                return 200, self.render(page)

        return 404, {"message": f"unhandled {method} {raw_path}"}

    def writes(self):
        return [r for r in self.requests if r[0] in ("POST", "PUT")]


class ConfluenceCliTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeConfluence()
        self.addCleanup(self.fake.stop)
        self.runbook = self.fake.add_page("Runbook", STORAGE_BODY)
        self.child = self.fake.add_page(
            "Runbook / Kafka",
            "<table><tr><td>topic</td><td>kafka notes</td></tr></table>",
            parent=self.runbook,
        )

    def run_cli(self, *args, token=GOOD_TOKEN, stdin=None, env_overrides=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("CONFLUENCE_")}
        env.update(
            {"CONFLUENCE_SERVER_URL": self.fake.url, "CONFLUENCE_API_KEY": token}
        )
        env.update(env_overrides or {})
        env = {k: v for k, v in env.items() if v is not None}
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            check=False,
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

    def write_body(self, content):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".xhtml", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
        self.addCleanup(os.unlink, f.name)
        return f.name

    # --- auth -----------------------------------------------------------------

    def test_test_accepts_valid_token(self):
        result = self.run_cli("--test")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Connected to Confluence as tester", result.stdout)

    def test_test_rejects_token_that_falls_back_to_anonymous(self):
        result = self.run_cli("--test", token="jira-token")
        self.assertEqual(result.returncode, 1)
        self.assertIn("anonymous", result.stdout)

    def test_missing_env_vars_explain_what_to_set(self):
        result = self.run_cli("--test", env_overrides={"CONFLUENCE_API_KEY": None})
        self.assertEqual(result.returncode, 1)
        self.assertIn("CONFLUENCE_API_KEY", result.stdout)
        self.assertNotIn("CONFLUENCE_SERVER_URL (", result.stdout)
        self.assertEqual(self.fake.requests, [])

    # --- reads ----------------------------------------------------------------

    def test_get_text_renders_readable_body(self):
        result = self.run_cli("--get", self.runbook)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Title: Runbook", result.stdout)
        self.assertIn("Restart the", result.stdout)
        self.assertIn("kubectl rollout restart deploy/worker", result.stdout)
        self.assertNotIn("<ac:structured-macro", result.stdout)

    def test_get_storage_json_returns_exact_xhtml(self):
        result = self.run_cli("--get", self.runbook, "--format", "storage", "--json")
        self.assertEqual(result.returncode, 0, result.stdout)
        page = json.loads(result.stdout)
        self.assertEqual(page["body"], STORAGE_BODY)
        self.assertEqual(page["version"], 1)
        self.assertEqual(
            page["url"], f"{self.fake.url}/pages/viewpage.action?pageId={self.runbook}"
        )

    def test_find_by_space_and_title(self):
        result = self.run_cli("--space", "DOC", "--title", "Runbook / Kafka", "--json")
        self.assertEqual(result.returncode, 0, result.stdout)
        page = json.loads(result.stdout)
        self.assertEqual(page["id"], self.child)
        self.assertEqual(page["parent_id"], self.runbook)

    def test_find_by_unknown_title_fails(self):
        result = self.run_cli("--space", "DOC", "--title", "Nope")
        self.assertEqual(result.returncode, 1)
        self.assertIn("No page titled 'Nope'", result.stdout)

    def test_get_missing_page_fails(self):
        result = self.run_cli("--get", "999999")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Failed", result.stdout)

    def test_search_lists_hits_with_clean_excerpt(self):
        result = self.run_cli("--search", 'space = DOC AND text ~ "kafka"')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(f"[{self.child}] Runbook / Kafka", result.stdout)
        self.assertNotIn(f"[{self.runbook}] Runbook\n", result.stdout)
        self.assertIn("...kafka...", result.stdout)
        excerpt_lines = [ln for ln in result.stdout.splitlines() if "kafka..." in ln]
        self.assertEqual(len(excerpt_lines), 1)
        self.assertNotIn("@@@", result.stdout)
        self.assertIn("Space: DOC | Version: 1 |", result.stdout)

    def test_children_lists_direct_children(self):
        result = self.run_cli("--children", self.runbook)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Found 1 child page(s)", result.stdout)
        self.assertIn("Space: DOC | Version: 1 |", result.stdout)
        self.assertIn(f"[{self.child}] Runbook / Kafka", result.stdout)

    # --- writes ---------------------------------------------------------------

    def test_create_from_stdin_under_parent(self):
        result = self.run_cli(
            "--create", "--space", "DOC", "--title", "New", "--parent", self.runbook, "--body-file", "-",
            stdin="<p>fresh</p>",
        )  # fmt: skip
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        created = [p for p in self.fake.pages.values() if p["title"] == "New"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["body"], "<p>fresh</p>")
        self.assertEqual(created[0]["parent"], self.runbook)

    def test_update_body_bumps_version_and_keeps_title(self):
        new_body = STORAGE_BODY.replace("worker", "dispatcher")
        result = self.run_cli(
            "--update",
            self.runbook,
            "--body-file",
            self.write_body(new_body),
            "--message",
            "rename",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("to version 2", result.stdout)
        page = self.fake.pages[self.runbook]
        self.assertEqual(page["body"], new_body)
        self.assertEqual(page["title"], "Runbook")
        put = self.fake.writes()[-1][2]
        assert put is not None
        self.assertEqual(put["version"]["message"], "rename")

    def test_update_title_only_keeps_body(self):
        result = self.run_cli("--update", self.runbook, "--title", "Runbook v2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        page = self.fake.pages[self.runbook]
        self.assertEqual(page["title"], "Runbook v2")
        self.assertEqual(page["body"], STORAGE_BODY)

    def test_update_refuses_stale_expected_version(self):
        self.fake.pages[self.runbook]["version"] = 5
        result = self.run_cli(
            "--update",
            self.runbook,
            "--body-file",
            self.write_body("<p>x</p>"),
            "--expected-version",
            "4",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("is at version 5, expected 4", result.stdout)
        self.assertEqual(self.fake.writes(), [])
        self.assertEqual(self.fake.pages[self.runbook]["body"], STORAGE_BODY)

    def test_update_keeps_full_width_layout(self):
        wide = self.fake.add_page("Wide", "<p>a</p>", full_width=True)
        result = self.run_cli(
            "--update", wide, "--body-file", self.write_body("<p>b</p>")
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.fake.pages[wide]["width"], "full-width")

    def test_update_page_without_width_property(self):
        result = self.run_cli(
            "--update", self.runbook, "--body-file", self.write_body("<p>b</p>")
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.fake.pages[self.runbook]["body"], "<p>b</p>")
        self.assertIn(self.fake.pages[self.runbook]["width"], (None, "fixed-width"))

    def test_update_with_identical_body_writes_nothing(self):
        result = self.run_cli(
            "--update", self.runbook, "--body-file", self.write_body(STORAGE_BODY)
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("unchanged", result.stdout)
        self.assertEqual(self.fake.writes(), [])

    def test_create_requires_space_title_and_body(self):
        result = self.run_cli("--create", "--title", "x")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.fake.requests, [])


if __name__ == "__main__":
    unittest.main()
