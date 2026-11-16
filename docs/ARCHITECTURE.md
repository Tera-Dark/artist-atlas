# Artist Atlas — Architecture & Product Decisions

> Status: living design note · 2026-11-16

## Product boundary

Artist Atlas is a personal, repository-first artist reference library. Its primary job is to turn a discovered artist into a reliably identified, searchable, reviewable record with useful public references. It is not a general-purpose image downloader, social network, ranking engine, or replacement for Danbooru.

The repository is the source of truth. GitHub Pages is a read-only public projection of committed data. The browser is an editor client, not a database. The old Windows collector is an optional candidate source and must not become a second source of truth.

## Core user journey

1. Capture a lead — enter a name, alias, profile URL, or import a candidate from the legacy collector.
2. Resolve identity — query Danbooru Artist records; show canonical name, aliases, ID, URLs, and status.
3. Review evidence — inspect the exact match and safe preview posts. A fuzzy/name-only match is a lead, never proof.
4. Curate — add personal category, style tags, score, notes, and optional featured status.
5. Commit — validate the full dataset, detect duplicates, then write a Git commit.
6. Browse — the public catalogue reads only committed repository data.
7. Maintain — re-check records when Danbooru data changes; preserve provenance and edit history through Git.

## System boundaries

```text
Candidate sources (manual / legacy Windows collector)
                    |
                    v
        Candidate review + identity resolution
                    |
          Danbooru read-only API
                    |
                    v
          Curated artist record editor
                    |
          GitHub Contents API (write)
                    |
                    v
             data/artists.json
                    |
          CI validation / Pages deploy
                    |
                    v
       GitHub Pages public catalogue
```

- GitHub repository: canonical records, schema, validation, documentation, version history.
- Danbooru: external identity evidence and public preview source; never the owner of personal curation fields.
- GitHub Pages: static read-only catalogue. No Python server, private database, or scheduled server process runs on Pages.
- Browser session: temporary GitHub credential and transient UI state only. Never store credentials in JSON, URLs, logs, commits, or localStorage.

## Data ownership

| Field group | Examples | Owner |
| --- | --- | --- |
| Stable identity | Danbooru artist ID, canonical name | Danbooru |
| Identity evidence | aliases, source URLs, last verification timestamp/status | Danbooru snapshot + curator review |
| Personal curation | display name, category, style tags, score, notes, featured | Curator |
| Preview cache | post IDs, preview URLs, preview refresh timestamp | Derived from Danbooru; disposable |
| Audit | added/updated timestamps, schema version | Artist Atlas |

A Danbooru ID is the stable external key. Do not use display names as primary keys. Do not silently merge two records because their names look similar.

## Verification policy

- Search with Danbooru's Artist API, not only the artist tag search.
- Preserve the selected artist ID and canonical name.
- Show is_banned and is_deleted prominently. Block normal publication of banned/deleted records; allow an explicit, separately documented exception only if the product later needs historical references.
- Exact canonical/alias matches are strong evidence. Fuzzy results are suggestions requiring manual confirmation.
- A missing General-rated preview is not proof that the Artist record is invalid.
- Query previews with an explicit safe-rating filter (rating:g). Do not store or render unrestricted preview results.
- Store source links and timestamps so stale metadata can be refreshed without losing personal notes.
- Respect Danbooru identification and rate-limit guidance; avoid parallel bursts and repeated full refreshes.

## Data quality and duplicate policy

1. id is an Artist Atlas stable record key.
2. danbooru_id must be unique across published records.
3. Canonical names are normalized for comparison, but the original source spelling is preserved.
4. Aliases are searchable metadata, not identity keys. Alias collisions are surfaced for human review rather than auto-merged.
5. A duplicate Danbooru ID updates the existing record; it must never create a second card.
6. Every write validates the complete next dataset before commit.
7. Concurrent edits must be detected against the latest repository version. A stale in-memory array must never overwrite newer records.

## GitHub write model and security

The static editor requires a user-supplied fine-grained PAT because GitHub Pages has no trusted server-side secret store. Keep this limitation explicit.

- Request access only to this repository and only the Contents: Read and write permission.
- Keep the token in memory for the active session; if session persistence is used, clear it on explicit disconnect and never put it in URLs or logs.
- Treat every rendered API string as untrusted text; escape HTML and validate URLs before using them in links or image sources.
- Do not add third-party scripts or analytics to the editor without a separate security review.
- GitHub Contents API writes are not a database transaction. Re-read the latest file, merge the intended operation by stable ID, and handle SHA conflicts with a bounded retry or ask the user to reload. Never blindly retry a stale full-file replacement.
- For broader community contributions, prefer Pull Requests with CI validation rather than asking contributors to use a write token in the public page.

## Repository layout

- data/artists.json — canonical curated records.
- data/artist.schema.json — machine-readable record contract.
- scripts/validate-data.mjs — dependency-free data and page sanity checks.
- .github/workflows/validate.yml — validation on pushes and pull requests.
- .github/workflows/pages.yml — publish the static docs/ site after validation.
- docs/ — static public catalogue and product documentation.
- Legacy Python collector files — optional candidate acquisition tool, not the catalogue database.

## Quality gates

Every change should pass:
- JSON parsing and schema/semantic checks.
- Unique record ID and Danbooru ID checks.
- Safe URL and safe-preview metadata checks.
- HTML duplicate-ID and inline JavaScript syntax checks.
- Desktop and mobile browser checks for empty, populated, loading, and error states.
- Keyboard checks for search, dialogs, and save flows.
- A manual review of Danbooru identity evidence before publishing a new artist.

## Deliberate non-goals for the first stable release

- No automated aesthetic score or AI ranking of artists.
- No copying/re-hosting artist images in this repository.
- No automatic identity merge based on fuzzy name similarity.
- No private backend or paid infrastructure.
- No multi-booru support until the Danbooru workflow is dependable.
- No large framework migration merely to reorganize a small static catalogue.

## Reference implementations and what to borrow

- Danbooru Artist API: use first-class Artist records, IDs, aliases, banned/deleted state, and source URLs. Do not infer artist identity from a tag string alone.
- Booru Tags Gallery: borrow the separation of data, API services, search, and presentation; load remote detail/preview data only when needed. Its large offline tag index is not necessary for this smaller curated catalogue.
- BooruBrowser: borrow the artist-centric discovery workflow and clear source adapters; do not inherit its local-first downloader architecture.
- Booru Studio: borrow the idea of following artists and recognizing artist metadata; do not copy its desktop/local infrastructure or add download-management features that are outside this project's purpose.
- GitHub Pages starter workflow: keep deployment least-privileged, deterministic, and separate from validation. The published artifact should contain only the static site.

These are selective design references, not dependencies or templates to copy wholesale.

## Roadmap

### P0 — trust and data integrity
- Schema + CI validation.
- Block banned/deleted Danbooru records from ordinary publishing.
- Prevent duplicate IDs and alias collisions from being silently accepted.
- Make writes merge-safe and conflict-aware.
- Validate preview URLs and retain source post IDs/timestamps.

### P1 — curator workflow
- Separate candidate inbox from published artists.
- Batch-import candidates from the legacy collector, then verify each candidate.
- Add duplicate suggestions and an explicit merge workflow.
- Add re-verify / refresh preview actions that preserve curator fields.
- Provide export/import with schema version and validation.

### P2 — community quality
- Add CONTRIBUTING guidance and issue templates.
- Accept curated additions through Pull Requests.
- Add CI summaries that explain invalid records and duplicate candidates.
- Add accessibility/performance checks and browser-level regression tests.