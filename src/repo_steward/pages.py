"""Public product, legal, and support pages for the hosted App."""

from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

public_router = APIRouter(include_in_schema=False)
_SUPPORT_EMAIL = "khlaifiabilel@icloud.com"
_EFFECTIVE_DATE = "July 30, 2026"


def _page(title: str, content: str) -> HTMLResponse:
    safe_title = escape(title)
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} | repo-steward</title>
</head>
<body>
  <main>
    <nav><a href="/">repo-steward</a> | <a href="/privacy">Privacy</a> |
      <a href="/terms">Terms</a> | <a href="/support">Support</a></nav>
    <h1>{safe_title}</h1>
    {content}
  </main>
</body>
</html>"""
    )


@public_router.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return _page(
        "Deterministic repository health",
        """
<p>repo-steward is a read-only GitHub App that evaluates repository documentation,
community files, automation, metadata, and lifecycle signals using transparent rules.</p>
<p>The free plan does not modify repositories, read file contents, or train models on
repository data.</p>
<p><a href="/docs">View the API documentation</a></p>
""",
    )


@public_router.get("/privacy", response_class=HTMLResponse)
async def privacy() -> HTMLResponse:
    return _page(
        "Privacy policy",
        f"""
<p><strong>Effective date:</strong> {_EFFECTIVE_DATE}</p>
<h2>Data processed</h2>
<p>repo-steward processes GitHub repository metadata, repository-relative file paths,
installation identifiers, account names, and signed webhook payloads needed to operate
the App. It does not fetch repository file contents.</p>
<h2>Purpose and retention</h2>
<p>Data is used only to authenticate installations, produce repository health reports,
respond to installation and plan lifecycle events, prevent abuse, and operate the
service. The current service has no application database, analytics service, or durable
webhook-payload storage. Request data is held in memory while a request is processed.</p>
<p>Operational logs contain request metadata, correlation identifiers, webhook delivery
identifiers, event names, installation identifiers, and status codes. They exclude
request bodies, access tokens, private keys, webhook secrets, and signatures. Hosting
provider logs are retained according to the provider's configured retention period.</p>
<h2>Sharing and security</h2>
<p>Data is shared only with GitHub and infrastructure providers required to operate the
service. Installation tokens are short-lived. Transport encryption and signed webhook
verification are required in production.</p>
<h2>Your choices</h2>
<p>You can stop future processing by uninstalling the App. For privacy questions or
deletion requests, contact <a href="mailto:{_SUPPORT_EMAIL}">{_SUPPORT_EMAIL}</a>.</p>
""",
    )


@public_router.get("/terms", response_class=HTMLResponse)
async def terms() -> HTMLResponse:
    return _page(
        "Terms of service",
        f"""
<p><strong>Effective date:</strong> {_EFFECTIVE_DATE}</p>
<p>By installing or using repo-steward, you agree to these terms. You must have authority
to install the App for each account and repository you connect.</p>
<h2>Service</h2>
<p>repo-steward provides informational repository-health reports through deterministic,
read-only checks. Reports are not security audits, legal advice, or guarantees of
software quality. You remain responsible for reviewing findings and deciding whether to
act on them.</p>
<h2>Free plan</h2>
<p>The current plan is provided without charge. Features, limits, and availability may
change with reasonable notice. A permanent free tier will remain available if optional
paid plans are introduced.</p>
<h2>Acceptable use</h2>
<p>Do not misuse the service, probe accounts without authorization, interfere with its
operation, evade limits, or use it in violation of law or GitHub's terms.</p>
<h2>Availability and termination</h2>
<p>The service is provided on an as-available basis without warranties to the extent
permitted by law. You may terminate these terms by uninstalling the App. Access may be
suspended for abuse, security risk, or legal requirements.</p>
<h2>Liability</h2>
<p>To the extent permitted by law, the publisher is not liable for indirect, incidental,
special, consequential, or punitive damages, or for loss of data, profits, or business
arising from use of the free service.</p>
<h2>Contact</h2>
<p>Questions about these terms can be sent to
<a href="mailto:{_SUPPORT_EMAIL}">{_SUPPORT_EMAIL}</a>.</p>
""",
    )


@public_router.get("/support", response_class=HTMLResponse)
async def support() -> HTMLResponse:
    return _page(
        "Support",
        f"""
<p>For installation, account, report, or availability help, email
<a href="mailto:{_SUPPORT_EMAIL}">{_SUPPORT_EMAIL}</a>.</p>
<p>Include the installation ID, delivery ID, or correlation ID when available. Never send
access tokens, private keys, webhook secrets, signatures, or private repository data.</p>
<p>Security vulnerabilities should use the same address with the subject
<strong>repo-steward security report</strong>. Do not disclose vulnerabilities publicly
before coordinated remediation.</p>
""",
    )
