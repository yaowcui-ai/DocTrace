# Managed knowledge operations

This optional corpus is `doctrace_managed_v1`. It has its own Docker Compose
project, port 9631, runtime directories and four SQL tables. Creating or editing
a document only saves text; indexing requires an explicit administrator action
and an explicit worker invocation. Managed documents are not automatically
available to the existing question-answering pipeline. Retrieval integration
and its evidence/citation policy must be approved and verified separately.

## Integration and setup

The application must include `app.knowledge.api.router`. The product deployment
migration must explicitly call
`app.knowledge.repository.metadata.create_all(engine)` alongside the product
metadata. There is no startup DDL, import-time network request, background
worker, or change to existing account/history/frozen-corpus tables.

Set `MANAGED_LIGHTRAG_URL=http://127.0.0.1:9631` and a dedicated
`MANAGED_LIGHTRAG_API_KEY` in the backend environment or its existing `.env`.
The worker accepts only loopback HTTP port 9631, without URL path, credentials,
query or fragment. It never falls back to `LIGHTRAG_URL`, frozen ports 9622,
9623, 9624 or 9630, or the frozen instance's API key. Do not print credentials.

After approval to start the optional service, from the repository root:

```powershell
docker compose --env-file .env -f deploy/compose.hr-managed.yml --profile managed up -d
```

The pinned image digest matches `compose.hr-v3.yml`; the project is
`doctrace-managed-v1`. Model/provider configuration is read from the existing
LightRAG `.env` mounted read-only. All writable storage is under
`runtime/doctrace_managed_v1/`. No frozen runtime directory is mounted.
Compose sets a separate workspace, title and API key. No service was started
and no real indexing or paid model call was performed during implementation.

Before every mutation and status poll the worker authenticates `/health`,
requiring `status=healthy`, `webui_title=DocTrace Managed Knowledge v1`, and
`configuration.workspace=doctrace_managed_v1`. Reported effective storage
workspaces must also agree. A different or incompatible server is refused.
The pinned image's health and document API schema still requires an authorized
real-instance compatibility check; local tests use the checked-in LightRAG
router contracts and mocked HTTP responses.

## API and document lifecycle

Every endpoint below uses existing session authentication plus the explicit
product administrator role. Missing roles and normal users cannot read either
document text or task metadata. All responses use `Cache-Control: no-store`.
Mutations require the configured exact trusted Origin and
`Content-Type: application/json`, including DELETE and POST index requests.
The API returns `{ "data": ... }`:

| Method | Path under `/api/v1/admin` | Result |
| --- | --- | --- |
| GET | `/documents` | Up to 500 latest documents; omits body text |
| POST | `/documents` | Save `{filename,content}` as draft; no index call |
| GET | `/documents/{uuid}` | Administrator-only body and metadata |
| PUT | `/documents/{uuid}` | Save a new draft version from `{filename,content}` |
| DELETE | `/documents/{uuid}` | Request retirement; no immediate upstream call |
| POST | `/documents/{uuid}/index` | Queue indexing; repeat returns existing task |
| GET | `/tasks` | Up to 500 latest tasks |
| GET | `/tasks/{uuid}` | Read one task |

Only `.txt` and `.md` filenames are allowed, without paths, drive names,
leading dots or control characters. Text must be valid UTF-8, nonblank, contain
no NUL and occupy at most 1 MiB. Normalized trimmed-content SHA-256 is globally
unique across saved versions, matching upstream whitespace normalization.
Repeated uploads return the existing document and never enqueue another index.
An update with the same body preserves the version and original filename.
Reusing a different existing version's hash is rejected. A retired document
is not automatically resurrected by a duplicate upload.

`managed_documents` stores stable UUID, corpus, latest version, active version
and state. `managed_document_versions` retains immutable text/hash, source
filename, version state, safe failure code, upstream ID and track ID.
`managed_index_jobs` stores each index/delete operation. `managed_worker_lock`
serializes all managed mutations across worker processes using a persistent
compare-and-set owner; queue claim also uses compare-and-set updates. Row locks
protect document version and task creation on MySQL. SQLite tests validate
portable contracts; a real MySQL concurrency smoke test remains a deployment check.

A new version does not replace `active_version` until a matching upstream
document is `processed`. Failed or pending versions leave the previous active
version recorded. Successful replacement queues old upstream versions for
retirement; asynchronous deletion can temporarily leave both versions upstream.
Consumers must not assume an upstream query automatically filters old versions.
Retirement of an indexed document retains local activation metadata until all
its upstream versions are confirmed absent from their original track status.
Drafts that were never submitted can retire locally.

## Explicit worker and failures

After approval to invoke potentially paid indexing APIs:

```powershell
.venv/Scripts/python.exe -m app.knowledge.worker --once
```

Each invocation handles at most one submit, deletion, or status poll. Invoke
again to advance a pending task. It does not run an internal retry loop.
Submission uses `POST /documents/text` with `{text,file_source}`; file sources
are `<document UUID>_v<version>_<safe filename>`. Status reads use
`GET /documents/track_status/{track_id}` and match the exact file source before
activation. Deletion uses `DELETE /documents/delete_document` with the recorded
upstream ID, `delete_file=false`, `delete_llm_cache=false`, then polls the
original track until that upstream ID is absent.

Document states include `draft`, `queued`, `indexing`, `processed`, `failed`,
`submission_unknown`, `retiring` and `retired`; task states additionally include
`claimed`, `polling` and `deleting`. Failures exposed to the API are fixed safe
codes. Upstream bodies, provider errors, URLs and credentials are not persisted
or returned as failure messages.

Transport errors, redirects, server errors and invalid success responses after
a mutation become `submission_unknown`. Such tasks are never automatically
resubmitted, including when the administrator repeats the index request.
Status outages preserve the track and retry only a read on the next invocation.
Explicit retries of deterministic failed submissions are allowed through index;
a failed processing result with an upstream ID requires reconciliation/retirement
before another upload, because partial vectors may exist upstream. Failed
deletions remain visible for operator intervention; no blind destructive retry
is attempted. There is no automatic reconciliation endpoint in this version.

If a worker crashes, the persistent global lock may remain owned, and a
`claimed`/`polling` task may remain unresolved. Stop every worker, inspect the
dedicated upstream by recorded source/track/ID, and back up the managed tables
before operator-directed repairs. Never automatically expire the lock or reset
an unresolved mutation to queued: the original upstream operation may have
committed. Managed querying is integrated with active-source filtering and before/after-generation version checks. Automatic crash reconciliation remains unimplemented; operators must verify unknown submissions before retrying.
