# Security policy

Maintained by Chockablock. Full policy: <https://chockablock.dev/security>

## Reporting a vulnerability

Email **support@chockablock.dev** with `SECURITY` in the subject line.

- Acknowledgement within **3 business days**
- Assessment with severity and intended remedy within **10 business days**

Please do not disclose publicly until a fix has shipped. Reporters who want
credit will be credited.

## Scope of this action

This action runs in **your** CI and authenticates as **you**, using an Atlassian
API token you supply from your own secret store. It talks to your Atlassian site
and to nothing else — there is no vendor endpoint, no telemetry and no third
party involved.

The token is never printed: a test asserts it does not appear in output. It is
passed to the Confluence REST API over HTTPS and is not written to disk.

If you find a way to make this action leak a credential, disclose a token in
logs, or send data anywhere other than the `base-url` you configured, please
report it using the process above — that is the highest-severity class of bug
this action can have.
