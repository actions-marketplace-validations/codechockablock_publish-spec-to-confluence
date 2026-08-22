# Publish API spec to Confluence

A GitHub Action that uploads your OpenAPI/Swagger file to a Confluence page as
an attachment, so the **OpenAPI Reference** macro on that page always renders
what is currently in `main`.

```yaml
name: Publish API reference
on:
  push:
    branches: [main]
    paths: ['docs/openapi.yaml']

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: codechockablock/publish-spec-to-confluence@v1
        with:
          base-url: https://acme.atlassian.net
          email: ${{ secrets.CONFLUENCE_EMAIL }}
          api-token: ${{ secrets.CONFLUENCE_API_TOKEN }}
          page-id: '2293761'
          file: docs/openapi.yaml
```

That is the whole integration. Git stays the source of truth; Confluence
becomes the reading room.

## Why publish, and not fetch

Most Confluence API-doc apps take a repository URL and fetch it when somebody
opens the page. That is convenient and it means your spec is sent to a third
party every time a page is read.

This does the opposite. Your CI pushes the file in, authenticating as you,
against your own Atlassian site. At view time the spec is already on the page,
so the app fetches nothing at all — which is what keeps it eligible for
Atlassian's **Runs on Atlassian** programme.

Nobody new is introduced by this. GitHub and Atlassian are both already on your
contract; this Action talks to those two and to nothing else.

The trade is honest and worth stating: freshness is **on push**, not on page
load. If the spec changes and CI does not run, the page is stale. In exchange,
your internal API surface is never handed to a vendor you did not name.

## Setup, once

1. **Create an API token** at
   `id.atlassian.com/manage-profile/security/api-tokens`. Add it to your
   repository as the secret `CONFLUENCE_API_TOKEN`, and your Atlassian account
   email as `CONFLUENCE_EMAIL`.
2. **Find the page id.** It is the number in the page URL:
   `/wiki/spaces/SPACE/pages/`**`2293761`**`/Your+Page`
3. **Put the macro on that page** once — insert `/openapi`, choose *Read a file
   attached to this page*, and pick the file after the first publish runs.

## Keep the filename stable

Re-uploading a file whose name already exists does not create a second
attachment: Confluence stores a **new version under the same attachment id**.
The macro is bound to that id, so every later publish updates the page silently
and nobody reopens the macro configuration.

Change the filename and you get a new id. The macro's binding misses and falls
back to matching by name — the reader is told this happened rather than being
shown different content without warning, but it is a step you can simply avoid
by leaving `attachment-name` alone.

## Inputs

| Input | Required | Notes |
|---|---|---|
| `base-url` | yes | `https://yoursite.atlassian.net`, no trailing slash |
| `email` | yes | the account the API token belongs to |
| `api-token` | yes | from Actions secrets — never inline it |
| `page-id` | yes | numeric, from the page URL |
| `file` | yes | path in your repo, e.g. `docs/openapi.yaml` |
| `attachment-name` | no | defaults to the file's basename; keep it stable |
| `comment` | no | version comment on the attachment |
| `fail-on-missing-file` | no | `false` to skip quietly when the file is absent |
| `mark-page` | no | `false` to skip the page marker — see below |

## The page marker

After a successful publish this action records a small content property on the
page, `oarender-spec`, saying the page holds a published spec. The Confluence
app reads it to decide where to show its **API spec** label — the line under
the page title naming the API, its version and when it was published.

It exists because of a constraint worth knowing about. Confluence gives an app
no way to hide that label on pages it has nothing to say about, so without a
marker the label would appear on **every page in your site** — every meeting
note, every retro — announcing an API spec that is not there. The marker
inverts it: the label appears where a spec was published and nowhere else.

**The app itself never writes anything.** It ships with a single read-only
scope, `read:attachment:confluence`, and that is the sentence its security
review rests on. The alternative was for the app to request
`write:content.property:confluence` so it could mark pages itself, which was
declined. This action already authenticates as you and already writes to the
page, so the marker costs no new app permission at all.

The property is `{"managedBy": "publish-spec-to-confluence"}` and carries no
filename, version or date — anything specific would be stale the moment the
next publish changed it. Its existence is the entire signal.

Set `mark-page: false` to publish without it. Your spec renders exactly the
same either way; only the label is affected. If the write is refused — a token
without permission, say — you get a warning and the publish still succeeds. The
spec is the job; the marker is not worth failing a pipeline over.

## Outputs

| Output | Notes |
|---|---|
| `attachment-id` | stable across republishes |
| `version` | attachment version after this publish |
| `changed` | `false` when the file was byte-identical and nothing was uploaded |

An unchanged file uploads nothing. Publishing on every green build would
otherwise fill the page history with versions that differ in no way, which
makes the history useless to the person auditing it later.

## Running the tests

```bash
python3 action/test_publish.py
```

No credentials needed — Confluence is stubbed. The tests cover the parts you
only notice when they break: that republishing reuses the same attachment id,
that an identical file uploads nothing, and that a bad token or page id
produces a sentence you can act on. The token is asserted never to appear in
output.
