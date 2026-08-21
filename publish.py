#!/usr/bin/env python3
"""
Publish a spec file to a Confluence page as an attachment.

WHY AN ATTACHMENT, AND WHY THE NAME MUST STAY STABLE
----------------------------------------------------
Uploading a file whose name already exists on the page does not create a
second attachment. Confluence stores a NEW VERSION under the SAME attachment
id. The OpenAPI Reference macro binds to that id, so re-publishing updates
what readers see without anyone reopening the macro configuration. Change the
filename and you get a new id, the macro's binding misses, and the page falls
back to matching by name — recoverable, but it is a rebind the reader is told
about rather than a silent swap. Keep the name stable.

WHY PUBLISH-TIME AND NOT VIEW-TIME
----------------------------------
This runs in your CI, authenticating as you, against your own Atlassian site.
The Confluence app never fetches anything: at view time the spec is already
sitting on the page. That is what keeps the app eligible for Runs on Atlassian.
An app that pulled from GitHub when the page loaded would be making a request
to a third party on every read, which is a different product with a different
security story.

No third party is involved here either. GitHub and Atlassian are both already
on your contract; nothing in this script talks to anyone else.
"""

import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 60


def fail(message, hint=None):
    print(f"::error::{message}", file=sys.stderr)
    if hint:
        print(f"       {hint}", file=sys.stderr)
    sys.exit(1)


def require(name):
    value = (os.environ.get(name) or "").strip()
    if not value:
        fail(f"Missing required input: {name.replace('OA_', '').lower().replace('_', '-')}")
    return value


def set_output(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{key}={value}\n")


def request(method, url, token_header, body=None, headers=None, raw=False):
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", token_header)
    req.add_header("X-Atlassian-Token", "nocheck")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            payload = response.read()
            return response.status, payload if raw else json.loads(payload or b"{}")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:400]
        return err.code, detail
    except urllib.error.URLError as err:
        fail(f"Could not reach Confluence: {err.reason}",
             "Check base-url. It should look like https://yoursite.atlassian.net")


def explain(status, detail, what):
    if status == 401:
        fail("Confluence rejected the credentials (401).",
             "Check `email` and `api-token`. The token must belong to that email, "
             "and API tokens are created at id.atlassian.com/manage-profile/security/api-tokens")
    if status == 403:
        fail("Authenticated, but not allowed to do that (403).",
             "The account needs permission to add attachments to this page.")
    if status == 404:
        fail("Confluence returned 404 for the page.",
             "Check `page-id`. It is the number in the page URL: "
             "/wiki/spaces/SPACE/pages/<page-id>/Title")
    fail(f"{what} failed with HTTP {status}: {detail}")


def multipart(filename, data, comment):
    """Build a multipart/form-data body without pulling in a dependency."""
    boundary = "----oaPublish" + hashlib.sha256(filename.encode()).hexdigest()[:24]
    sep = f"--{boundary}\r\n".encode()
    parts = [
        sep,
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: application/octet-stream\r\n\r\n",
        data,
        b"\r\n",
        sep,
        b'Content-Disposition: form-data; name="comment"\r\n\r\n',
        comment.encode("utf-8"),
        b"\r\n",
        sep,
        b'Content-Disposition: form-data; name="minorEdit"\r\n\r\n',
        b"true\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main():
    base = require("OA_BASE_URL").rstrip("/")
    email = require("OA_EMAIL")
    token = require("OA_API_TOKEN")
    page_id = require("OA_PAGE_ID")
    file_path = require("OA_FILE")
    comment = os.environ.get("OA_COMMENT") or "Published from GitHub Actions"
    fail_on_missing = (os.environ.get("OA_FAIL_ON_MISSING") or "true").lower() != "false"

    if not page_id.isdigit():
        fail(f"page-id must be numeric, got {page_id!r}",
             "It is the number in the page URL, not the space key or the title.")

    if not os.path.isfile(file_path):
        if fail_on_missing:
            fail(f"Spec file not found: {file_path}")
        print(f"::notice::{file_path} not present; nothing to publish.")
        set_output("changed", "false")
        return

    name = (os.environ.get("OA_ATTACHMENT_NAME") or "").strip() or os.path.basename(file_path)
    with open(file_path, "rb") as handle:
        data = handle.read()
    if not data:
        fail(f"{file_path} is empty; refusing to publish an empty spec.")

    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    header = f"Basic {auth}"

    # 1. Is this file already on the page? Match by name — that is the identity
    #    that keeps the macro's binding stable across publishes.
    query = urllib.parse.urlencode({"filename": name})
    status, body = request(
        "GET", f"{base}/wiki/rest/api/content/{page_id}/child/attachment?{query}", header
    )
    if status != 200:
        explain(status, body, "Looking up existing attachments")

    existing = (body.get("results") or [None])[0] if isinstance(body, dict) else None

    # 2. If it is there and byte-identical, stop. Publishing an unchanged file
    #    would burn a version number and make the page history unreadable for
    #    the humans who have to audit it later.
    if existing:
        att_id = existing.get("id")
        dl = ((existing.get("_links") or {}).get("download")) or ""
        if dl:
            code, current = request("GET", f"{base}/wiki{dl}", header, raw=True)
            if code == 200 and isinstance(current, bytes) and current == data:
                print(f"::notice::{name} is already current on page {page_id}; nothing uploaded.")
                set_output("attachment-id", att_id)
                set_output("version", str((existing.get("version") or {}).get("number", "")))
                set_output("changed", "false")
                return

        payload, content_type = multipart(name, data, comment)
        status, body = request(
            "POST",
            f"{base}/wiki/rest/api/content/{page_id}/child/attachment/{att_id}/data",
            header, body=payload, headers={"Content-Type": content_type},
        )
        if status not in (200, 201):
            explain(status, body, "Updating the attachment")
        result = body if isinstance(body, dict) else {}
        action = "Updated"
    else:
        payload, content_type = multipart(name, data, comment)
        status, body = request(
            "POST",
            f"{base}/wiki/rest/api/content/{page_id}/child/attachment",
            header, body=payload, headers={"Content-Type": content_type},
        )
        if status not in (200, 201):
            explain(status, body, "Creating the attachment")
        result = (body.get("results") or [{}])[0] if isinstance(body, dict) else {}
        action = "Created"

    att_id = result.get("id", "")
    version = str(((result.get("version") or {}).get("number", "")))
    size = len(data)
    print(f"::notice::{action} {name} ({size} bytes) on page {page_id} "
          f"[attachment {att_id}, version {version}]")
    set_output("attachment-id", att_id)
    set_output("version", version)
    set_output("changed", "true")


if __name__ == "__main__":
    main()
