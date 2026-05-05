# Persisting Firefly RAG corpora on Azure Container Apps

Copyright 2026 Firefly Software Foundation. Licensed under the Apache License 2.0.

The `corpus_rag` MCP tools store each corpus as a SQLite file at
`${CORPUS_ROOT}/<corpus_id>/corpus.sqlite` (chunks + FTS5 + vec0 + ledger
co-resident, per the `SqliteVecVectorStore` design). For any non-toy
deployment **operators must override the default `CORPUS_ROOT`** — the
default `/tmp/firefly/corpora` is ephemeral and per-replica on Container
Apps, which means a cold start wipes the corpus.

## Recommended setup: Azure Files volume

1. Provision an Azure Files share. Microsoft's storage-mounts guide is
   the source of truth for the exact CLI invocations:
   <https://learn.microsoft.com/azure/container-apps/storage-mounts>
2. Register the share with the Container Apps environment
   (`az containerapp env storage set ... --azure-file-share-name corpora`).
3. Mount it on the `firefly-mcp` Container App at `/mnt/corpora`.
4. Set the env var on the app:

       az containerapp update --name firefly-mcp --resource-group rg-firefly \
           --set-env-vars CORPUS_ROOT=/mnt/corpora

The MCP tools will now write to and read from the durable share. Cold
starts no longer lose state.

## Multi-replica caveat

`SqliteCorpus` is single-writer. Two replicas writing the *same* corpus
will corrupt the SQLite file (FTS5 + vec0 are not safe under concurrent
writers from different processes). Two safe operating modes:

- **Single-replica ingest path.** Set `--max-replicas 1` on the Container
  App (or split ingest onto a dedicated single-replica app). Reads can
  fan out across replicas safely.
- **Per-replica corpus partitioning.** If multiple replicas must serve
  ingest, arrange that any given `corpus_id` only lands on one replica
  (e.g. partition routing in the calling agent). The framework does not
  enforce this — operators must.

## Other env vars consumed by the MCP tools

| Variable | Purpose | Example |
|---|---|---|
| `CORPUS_ROOT` | Where corpora live on disk. | `/mnt/corpora` |
| `EMBEDDING_MODEL` | Embedder spec, `provider:model`. | `azure:text-embedding-3-small` |
| `EXPANSION_MODEL` | LLM for query expansion. | `anthropic:claude-haiku-4-5-20251001` |
| `ANSWER_MODEL` | LLM for answer synthesis. | `anthropic:claude-sonnet-4-6` |
| `RERANK_MODEL` | LLM for listwise reranking. | `anthropic:claude-haiku-4-5-20251001` |

The Azure embedder additionally needs `EMBEDDING_BINDING_HOST` and
`EMBEDDING_BINDING_API_KEY`, mirroring the example CLI's conventions
(see `examples/corpus_search/cli.py`).

## SharePoint ingestion auth

`ingest_corpus_sharepoint` uses `azure.identity.aio.ManagedIdentityCredential`
to obtain a Microsoft Graph token. The Container App's user-assigned
managed identity (`firefly-mcp-mi`) needs `Sites.Selected` (preferred)
or `Sites.Read.All` granted on the target SharePoint site. Avoid
broad `.All` permissions when a per-site grant suffices.

## Verifying persistence

After mounting the share and pointing `CORPUS_ROOT` at it:

```bash
# From inside any container with the same mount:
ls /mnt/corpora                       # lists corpus_id directories
sqlite3 /mnt/corpora/<corpus_id>/corpus.sqlite '.tables'
# Expect: chunks, ingest_ledger, vec_chunks, ...
```

Round-trip: ingest a small folder via the MCP tool, restart the
Container App (`az containerapp revision restart ...`), then call
`corpus_query` with a question that should hit the ingested document.
A grounded answer confirms persistence.
