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
