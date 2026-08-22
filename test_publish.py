#!/usr/bin/env python3
"""
Tests for publish.py, with Confluence replaced by a stub.

The behaviours that matter are the ones a user never sees until they go wrong:
that re-publishing reuses the SAME attachment id (so the macro's binding
survives), that an unchanged file uploads nothing at all, and that a wrong
token or page id produces a sentence a person can act on instead of a stack
trace. All three are checked here without touching a real site.
"""
import io, json, os, subprocess, sys, tempfile, textwrap, unittest, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))

STUB = textwrap.dedent('''
    import io, json, sys, urllib.error, urllib.request
    STATE = json.loads(__import__("os").environ["STUB"])
    CALLS = []
    class R(io.BytesIO):
        status = 200
        def __init__(self, b): super().__init__(b)
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake(req, timeout=None):
        url, method = req.full_url, req.method
        CALLS.append((method, url.split("/wiki")[-1].split("?")[0]))
        code = STATE.get("force_code")
        if code:
            raise urllib.error.HTTPError(url, code, "no", {}, io.BytesIO(b"denied"))
        if "/properties" in url:
            pcode = STATE.get("property_code")
            if pcode:
                raise urllib.error.HTTPError(url, pcode, "no", {}, io.BytesIO(b"nope"))
            return R(json.dumps({"key": "oarender-spec", "id": "prop1"}).encode())
        if method == "GET" and "child/attachment" in url and "/data" not in url:
            return R(json.dumps({"results": STATE["existing"]}).encode())
        if method == "GET":
            return R(STATE["current_bytes"].encode())
        body = {"id": "att999", "version": {"number": 2}}
        if url.endswith("child/attachment"):
            body = {"results": [{"id": "attNEW", "version": {"number": 1}}]}
        return R(json.dumps(body).encode())
    urllib.request.urlopen = fake
    import publish
    try:
        publish.main()
    finally:
        sys.stderr.write("CALLS=" + json.dumps(CALLS) + "\\n")
''')


def run(existing, current_bytes="", file_bytes="spec: v1", force_code=None, page_id="12345",
        mark_page="true", property_code=None):
    with tempfile.TemporaryDirectory() as tmp:
        spec = os.path.join(tmp, "openapi.yaml")
        with open(spec, "w") as fh:
            fh.write(file_bytes)
        out = os.path.join(tmp, "gh_out")
        open(out, "w").close()
        driver = os.path.join(tmp, "driver.py")
        with open(driver, "w") as fh:
            fh.write(STUB)
        env = dict(os.environ,
            PYTHONPATH=HERE,
            STUB=json.dumps({"existing": existing, "current_bytes": current_bytes,
                             "force_code": force_code, "property_code": property_code}),
            OA_BASE_URL="https://acme.atlassian.net", OA_EMAIL="a@b.c",
            OA_API_TOKEN="secret-token-value", OA_PAGE_ID=page_id,
            OA_FILE=spec, OA_ATTACHMENT_NAME="", OA_COMMENT="ci",
            OA_FAIL_ON_MISSING="true", OA_MARK_PAGE=mark_page, GITHUB_OUTPUT=out)
        p = subprocess.run([sys.executable, driver], capture_output=True, text=True, env=env)
        with open(out) as fh:
            outputs = dict(l.split("=", 1) for l in fh.read().splitlines() if "=" in l)
        return p, outputs


class T(unittest.TestCase):
    def test_republish_reuses_the_same_attachment_id(self):
        """The macro binds to the id. A new id would break the binding."""
        p, out = run([{"id": "att777", "version": {"number": 4},
                       "_links": {"download": "/download/old"}}], current_bytes="spec: v0")
        self.assertIn("/child/attachment/att777/data", p.stderr, p.stderr)
        self.assertEqual(out.get("changed"), "true")

    def test_identical_file_uploads_nothing(self):
        p, out = run([{"id": "att777", "version": {"number": 4},
                       "_links": {"download": "/download/old"}}], current_bytes="spec: v1")
        self.assertEqual(out.get("changed"), "false")
        self.assertEqual(out.get("attachment-id"), "att777")
        self.assertNotIn("/data", p.stderr.split("CALLS=")[-1])

    def test_first_publish_creates(self):
        p, out = run([])
        self.assertEqual(out.get("changed"), "true")
        self.assertEqual(out.get("attachment-id"), "attNEW")

    def test_bad_credentials_explain_themselves(self):
        p, _ = run([], force_code=401)
        self.assertIn("rejected the credentials", p.stderr)
        self.assertIn("api-token", p.stderr)
        self.assertNotIn("secret-token-value", p.stderr)

    def test_wrong_page_id_explains_itself(self):
        p, _ = run([], force_code=404)
        self.assertIn("page-id", p.stderr)

    def test_non_numeric_page_id_refused_before_any_request(self):
        p, _ = run([], page_id="SPACEKEY")
        self.assertIn("must be numeric", p.stderr)
        self.assertNotIn("CALLS=[[", p.stderr.replace(" ", ""))

    def test_empty_spec_refused(self):
        p, _ = run([], file_bytes="")
        self.assertIn("empty", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class Marker(unittest.TestCase):
    """
    The content property that tells the Confluence app where its page label
    belongs.

    The app reads this through a display condition, so its ABSENCE is what
    keeps the label off the thousands of pages in a site that have no spec.
    That makes writing it a contract, not a detail: the label is accurate
    because this runs, and inaccurate the moment it silently stops.

    It is also the reason the app still asks for exactly one read-only scope.
    Writing the marker from CI uses the customer's own credentials; the
    alternative was `write:content.property:confluence` on the app itself.
    """

    def test_marks_the_page_after_creating_an_attachment(self):
        p, out = run([])
        self.assertIn("/api/v2/pages/12345/properties", p.stderr, p.stderr)
        self.assertEqual(out.get("changed"), "true")

    def test_marks_the_page_after_updating_an_attachment(self):
        p, _ = run([{"id": "att777", "version": {"number": 4},
                     "_links": {"download": "/download/old"}}], current_bytes="spec: v0")
        self.assertIn("/api/v2/pages/12345/properties", p.stderr, p.stderr)

    def test_marks_the_page_even_when_nothing_was_uploaded(self):
        """
        The case that would otherwise strand the longest-standing users. A page
        published before this action learned to mark pages stays byte-identical
        forever, so gating the marker on `changed` would mean it never got one.
        """
        p, out = run([{"id": "att777", "version": {"number": 4},
                       "_links": {"download": "/download/old"}}], current_bytes="spec: v1")
        self.assertEqual(out.get("changed"), "false")
        self.assertIn("/api/v2/pages/12345/properties", p.stderr, p.stderr)

    def test_mark_page_false_writes_nothing(self):
        p, out = run([], mark_page="false")
        self.assertNotIn("/properties", p.stderr, p.stderr)
        self.assertEqual(out.get("changed"), "true")

    def test_a_refused_marker_warns_but_does_not_fail_the_publish(self):
        """
        The attachment is the job. A site that will not take the property must
        not break somebody's pipeline over a label.
        """
        p, out = run([], property_code=403)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(out.get("changed"), "true")
        self.assertIn("::warning::", p.stdout + p.stderr)

    def test_an_existing_marker_is_not_an_error(self):
        """409 means the marker is already there, which is the desired state."""
        p, out = run([], property_code=409)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("::warning::", p.stdout)
        self.assertEqual(out.get("changed"), "true")

    def test_the_marker_carries_nothing_that_can_go_stale(self):
        """
        Its existence is the whole signal. A filename or version in the value
        would be wrong the moment the next publish changed it, and a stale
        marker is precisely the failure this approach exists to avoid.
        """
        import publish
        self.assertEqual(publish.SPEC_MARKER_KEY, "oarender-spec")

