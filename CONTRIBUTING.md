# Contributing to Artist Atlas

Thanks for helping improve the catalogue.

## Adding an artist

The preferred contribution is a Pull Request that updates data/artists.json.

1. Find the artist in the Danbooru Artist API or artist page.
2. Confirm the canonical Artist ID and canonical name. Do not infer identity from a similar-looking tag.
3. Check that the record is not marked banned or deleted.
4. Search the current catalogue for the Danbooru ID, canonical name, and aliases before adding a record.
5. Preserve existing personal notes, categories, tags, and score when refreshing source metadata.
6. Add only HTTPS preview URLs from Danbooru-controlled hosts, and use General-rated preview posts.
7. Run node scripts/validate-data.mjs.
8. Explain the identity evidence and the reason for adding the artist in the Pull Request.

## Data rules

- One published record per Danbooru Artist ID.
- Never auto-merge records based only on similar names.
- Keep canonical source identity separate from personal curation.
- Do not add downloaded image files or re-host artist works in this repository.
- Do not add API keys, browser cookies, tokens, account data, or private collection files.
- If an alias appears to belong to two artists, flag it for manual review instead of silently assigning it.

## Scope

Artist Atlas is a curated artist reference library. Changes should improve discovery, identity verification, curation, search, accessibility, or maintenance. General-purpose image downloading, unrelated social features, and automated aesthetic ranking are out of scope unless discussed in an issue first.

## Reporting a problem

Please include the page or data record involved, the steps to reproduce, expected behavior, and actual behavior. Never include credentials or private account information.
