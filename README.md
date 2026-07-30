# repo-steward

**Private beta.** repo-steward is a small, deterministic API for explaining repository
health gaps across a portfolio. Repository hygiene is often assessed by opaque scores
or manual spreadsheets; this service turns a normalized metadata and path snapshot into
repeatable facts, recommendations, and bounded scores.

repo-steward is read-only. It never deletes, archives, renames, changes visibility, or
otherwise modifies a repository. The MVP has no database, frontend, or background jobs.

## Principles and scope

- Deterministic facts are separate from recommendations; no AI-generated claims.
- Every finding has a stable rule ID, category, severity, evidence, recommendation,
  `source="deterministic"`, and an explicit `can_autofix` value.
- Analysis and inventory do not require GitHub credentials, but all `/api/v1` routes
  require `X-Repo-Steward-Key` whenever `REPO_STEWARD_API_KEY` is configured.
- GitHub access is optional, read-only, bounded, and isolated behind one client.
- Archived repositories are identified but are not penalized for intentional inactivity.
- Secrets and payload contents are excluded from application logs.

The MVP checks README, license, security policy, contribution guide, code of conduct,
issue templates, pull request template, CI workflow, description, topics, and archived
status. Inventory counts originals, forks, archived, private, public, missing
descriptions, and missing licenses.

## Architecture

```text
HTTP client / GitHub webhook
            |
      FastAPI routes  <--- HMAC verification before JSON parsing
            |
   pure analysis services
            |
 domain models + fixed rules

Optional owner endpoint ---> bounded read-only GitHub REST client
                                  ^
                     token or GitHub App token exchange helper
```

`models.py`, `rules.py`, and `services.py` have no network dependency. `github.py` owns
REST pagination and safe tree traversal. `auth.py` creates short-lived App JWTs and
exchanges installation tokens. `webhooks.py` performs constant-time signature checks.
`routes.py` and `app.py` provide transport, validation, and correlation-aware logging.

## Local setup

Requires Python 3.12 or newer.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/uvicorn repo_steward.app:app --reload
```

Or run `make install`, then `make check`. Copy `.env.example` to `.env` only when local
GitHub or webhook integration is needed. Do not use production credentials for tests.
For a container, use `docker compose up --build`.

## API examples

Health is always public. The examples assume an API key is configured:

```bash
curl http://localhost:8000/healthz

curl -X POST http://localhost:8000/api/v1/analyze \
  -H "X-Repo-Steward-Key: $REPO_STEWARD_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "owner": "example",
    "name": "widget",
    "description": "A sample widget",
    "license": "Apache-2.0",
    "topics": ["python"],
    "file_paths": ["README.md", "LICENSE", ".github/workflows/ci.yml"]
  }'

curl -X POST http://localhost:8000/api/v1/inventory \
  -H "X-Repo-Steward-Key: $REPO_STEWARD_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"snapshots":[{"owner":"example","name":"widget"}]}'
```

With `REPO_STEWARD_GITHUB_TOKEN` and an explicit comma-separated
`REPO_STEWARD_GITHUB_ALLOWED_OWNERS` configured, the optional
`POST /api/v1/github/owners/{owner}/analyze` endpoint lists an allowed owner's
repositories and analyzes their metadata and paths. It has an aggregate timeout in
addition to per-request and traversal bounds. Upstream details are never returned.

## Scoring

Each active repository starts at 100 in four categories. Triggered rules subtract the
fixed points below; category scores have a floor of zero. The total is the rounded
weighted average, bounded to 0-100.

| Category | Total weight | Rule deductions |
| --- | ---: | --- |
| Documentation | 30% | README 30, license 25 |
| Community | 30% | security 15, contributing 10, conduct 10, issues 10, PR 10 |
| Automation | 25% | CI workflow 30 |
| Metadata | 15% | description 15, topics 10 |

For example, missing only a README yields documentation 70 and a total of 91:
`round(70*0.30 + 100*0.30 + 100*0.25 + 100*0.15)`. Evidence records only observed
snapshot facts. Recommendations state possible action and are not presented as facts.
Archived repositories receive an informational lifecycle finding with `scored=false`,
`total_score=null`, and empty category scores. They cannot be mistaken for perfect.

Rules are versioned in code. Changing an ID, predicate, deduction, or weight is a
behavioral API change requiring tests and release notes.

## GitHub App registration

Registration is an operator action; this project does not register an App. In GitHub,
open **Settings > Developer settings > GitHub Apps > New GitHub App**, set the webhook
URL to `https://YOUR-HOST/webhooks/github`, generate a random webhook secret, and store
the downloaded private key outside the repository. Configure the App ID and either
`REPO_STEWARD_GITHUB_PRIVATE_KEY_PATH` or `REPO_STEWARD_GITHUB_PRIVATE_KEY`, never both.

Exact minimal repository permissions:

- **Metadata: Read-only** (mandatory GitHub App permission; repository identity/status)
- **Contents: Read-only** (Git Trees and default-branch paths)

No organization or account permissions are required for the MVP. Subscribe only to:

- **Installation** (installation lifecycle)
- **Push** (future read-only re-analysis trigger; currently accepted without action)
- **Ping** is sent by GitHub when configuring the webhook and requires no subscription.

Do not grant Administration, Actions, Issues, Pull requests, or any write permission.
The current owner endpoint accepts a configured token directly; production App wiring
should select an installation and use `create_app_jwt` plus
`exchange_installation_token` before constructing the read-only client.

## Security model

- Webhook HMAC SHA-256 is checked with constant-time comparison on raw bytes before JSON
  parsing. Missing or invalid signatures receive `401`.
- Production startup requires an API key of at least 32 characters. If a webhook secret
  is configured in production it must also have at least 32 characters. API key checks
  compare fixed-length SHA-256 digests in constant time; webhooks remain separately HMAC
  authenticated and `/healthz` remains public.
- A receive-stream body limit (1 MiB by default, configurable up to 16 MiB) rejects both
  declared and chunked oversized bodies before route parsing.
- REST identifiers are validated before URL composition. Pagination and recursive tree
  traversal have configurable hard limits. Truncated recursive trees are traversed
  breadth-first through non-recursive tree reads.
- The GitHub client implements GET operations only. The only POST in GitHub integration
  is GitHub's installation-token exchange endpoint.
- App JWTs expire in nine minutes and installation tokens are returned only to the
  caller. Secret settings use Pydantic secret types and are never logged.
- The GitHub API URL is restricted to HTTPS `api.github.com`; HTTP localhost is allowed
  only in the test environment. The container runs unprivileged; Compose binds only to
  `127.0.0.1`, uses a read-only filesystem, disables privilege escalation, and sets CPU,
  memory, and PID limits.
- Production operators must terminate TLS, limit request body size at the proxy, rotate
  credentials, restrict network egress, and define log retention.

See [SECURITY.md](SECURITY.md) and [PRIVACY.md](PRIVACY.md).

## Limitations

- File presence does not establish document quality, policy enforcement, or workflow
  success. The service does not read file contents.
- The generic user-repositories API may not represent every repository visible to an
  installation. Installation-aware enumeration is a post-MVP concern.
- No event deduplication or durable processing exists because there is no persistence.
- The webhook accepts only `ping`, `installation`, and `push`, but deliberately performs
  no action. Valid signed deliveries can be replayed; persistence-based deduplication is
  deferred until the service has durable state.
- CI builds the image and emits a BuildKit SBOM attestation. It does not yet run a
  vulnerability scanner; add a reputable scanner only after its exact action SHA is
  independently verified, without adding write permissions.

## Reproducible builds

`requirements.lock` is generated with hashes by `make lock` using `uv`. Docker installs
that runtime lock with `--require-hashes`, then installs the local package with
`--no-deps`. CI regenerates the lock and fails on drift. The Python base image is pinned
by digest. To update it, pull the intended tag, inspect its `RepoDigests`, review upstream
release notes and scan results, update both tag and digest, regenerate the lock, and run
the complete validation suite and container build.

- Rules do not yet account for organization-level community health files.
- Scores are hygiene indicators, not security, maintainability, or activity ratings.

## Roadmap and Marketplace path

1. Validate rules and weighting with private-beta portfolio owners.
2. Add installation-aware repository enumeration and explicit rescan orchestration.
3. Add opt-in, documented persistence only if durable history is proven necessary.
4. Add organization policy overlays and versioned report exports.
5. Complete threat modeling, operational SLOs, privacy terms, support contacts, billing,
   installation onboarding, webhook redelivery/idempotency, and GitHub's Marketplace
   verification requirements before any Marketplace listing.

Marketplace publication is not part of this MVP. The App must remain private until the
placeholder contacts are replaced and legal, security, privacy, and support reviews are
complete.

## License

Apache License 2.0. See [LICENSE](LICENSE).
