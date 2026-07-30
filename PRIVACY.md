# Privacy

## MVP data handling

repo-steward processes repository metadata and file paths supplied directly to its API
or fetched through a configured GitHub credential. It also processes GitHub webhook
delivery IDs, event names, installation and account identifiers, Marketplace plan
identifiers, and JSON payloads. It does not fetch file contents.
Requests exceeding the configured body limit are rejected before application parsing.

The MVP has no database, queue, analytics service, or application-level retention.
Request bodies and GitHub payloads are held only in process memory for the request.
Structured logs contain request method, path, status, correlation ID, and webhook
delivery/event identifiers. They intentionally exclude request bodies, tokens, private
keys, webhook secrets, and signature values. Deployment platform log retention remains
the operator's responsibility.
Correlation IDs are generated when a supplied value is absent or fails the restricted
128-character format. Exception logs use fixed messages and allow-listed metadata only.

GitHub receives requests made with the operator-configured credential and applies its
own privacy terms. Do not submit third-party data without authorization. Before a hosted
beta, define a retention schedule, deletion process, data controller contact, and
subprocessor list. The hosted service exposes the current user-facing notice at `/privacy`.
