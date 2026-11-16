import fs from "node:fs";

const candidates = JSON.parse(fs.readFileSync("data/candidates.json", "utf8"));
const verification = JSON.parse(fs.readFileSync("data/verified-artists.json", "utf8"));
const catalogue = JSON.parse(fs.readFileSync("data/artists.json", "utf8"));
const verifiedAt = verification.checked_at || new Date().toISOString();
const artists = Array.isArray(catalogue.artists) ? catalogue.artists : [];
const indexByDanbooruId = new Map(artists.map((artist, index) => [String(artist.danbooru_id), index]));
const resultsByCandidate = new Map(verification.results.map((result) => [result.candidate_id, result]));
let added = 0;
let refreshed = 0;

for (const candidate of candidates.candidates) {
  const result = resultsByCandidate.get(candidate.id);
  if (!result || !["verified", "verified_no_previews"].includes(result.status)) continue;
  if (!Number.isInteger(result.artist_id) || result.artist_id <= 0 || !result.canonical_name || result.is_banned || result.is_deleted) continue;

  const key = String(result.artist_id);
  const existingIndex = indexByDanbooruId.get(key);
  const previous = existingIndex === undefined ? null : artists[existingIndex];
  const previewUrls = (result.previews || []).map((post) => post.preview_url || post.large_url).filter(Boolean);
  const previewPostIds = (result.previews || []).map((post) => post.id).filter(Number.isInteger);
  const aliases = [...new Set([...(previous?.aliases || []), ...(result.aliases || []), candidate.query])].filter((alias) => alias && alias !== result.canonical_name);
  const entry = {
    id: previous?.id || "artist-" + key,
    name: previous?.name || result.canonical_name,
    danbooru_id: key,
    danbooru_name: result.canonical_name,
    aliases,
    category: previous?.category || "未分类",
    tags: previous?.tags || [],
    score: previous?.score ?? null,
    note: previous?.note || "",
    post_count: result.post_count || previous?.post_count || 0,
    preview_urls: previewUrls.length ? previewUrls : (previous?.preview_urls || []),
    preview_post_ids: previewPostIds.length ? previewPostIds : (previous?.preview_post_ids || []),
    danbooru_url: result.artist_url || "https://danbooru.donmai.us/artists/" + key,
    danbooru_verified_at: result.checked_at || verifiedAt,
    preview_updated_at: result.checked_at || verifiedAt,
    added_at: previous?.added_at || verifiedAt,
    updated_at: verifiedAt,
    featured: previous?.featured || false,
  };

  if (existingIndex === undefined) {
    indexByDanbooruId.set(key, artists.length);
    artists.push(entry);
    added += 1;
  } else {
    artists[existingIndex] = entry;
    refreshed += 1;
  }
}

catalogue.updated_at = verifiedAt;
catalogue.artists = artists;
fs.writeFileSync("data/artists.json", JSON.stringify(catalogue, null, 2) + "\n");
console.log(`Catalogue updated: ${added} added, ${refreshed} refreshed, ${artists.length} published artist(s).`);
