# Security Policy

## Private beta

repo-steward is in private beta. Do not report vulnerabilities in a public issue.
Send a minimal reproduction to **khlaifiabilel@icloud.com**.

We will acknowledge a report within five business days. Supported releases are the
current mainline release only.

## Scope

Relevant reports include webhook authentication bypass, credential disclosure,
unbounded GitHub API traversal, unsafe path handling, and dependency vulnerabilities.
Never include real access tokens, private keys, webhook secrets, or third-party data in
a report. Use generated test credentials.

## Deployment boundaries

Production configuration validation requires a 32-character API key and rejects a
configured webhook secret shorter than 32 characters. Health is public; `/api/v1` uses
the API key; the webhook uses its own HMAC secret. Compose exposes the service only on
loopback and is not a claim that a deployment has been penetration tested or certified.
Terminate TLS at a reviewed proxy and keep the explicit owner allow-list minimal.

The current webhook has no side effects and no replay store. A valid signed delivery can
be replayed, so do not add side effects until durable delivery-ID deduplication exists.
