import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const errors = [];
const warnings = [];
const fail = (message) => errors.push(message);
const isDate = (value) => typeof value === "string" && !Number.isNaN(Date.parse(value));
const normalize = (value) => String(value ?? "").normalize("NFKC").trim().toLocaleLowerCase().replace(/[\s._-]+/g, "_");

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); }
  catch (error) { fail(path.relative(root, file) + ": invalid JSON — " + error.message); return null; }
}

const data = readJson(path.join(root, "data", "artists.json"));
const schema = readJson(path.join(root, "data", "artist.schema.json"));
if (!data || !schema) fail("Catalogue or schema could not be loaded.");

if (data) {
  if (Object.keys(data).some(key => !["version", "updated_at", "artists"].includes(key))) fail("data/artists.json: unexpected top-level property.");
  if (data.version !== 1) fail("data/artists.json: version must be 1.");
  if (!isDate(data.updated_at)) fail("data/artists.json: updated_at must be an ISO date-time.");
  if (!Array.isArray(data.artists)) fail("data/artists.json: artists must be an array.");
  const ids = new Set();
  const danbooruIds = new Set();
  const aliases = new Map();
  for (const [index, artist] of (Array.isArray(data.artists) ? data.artists : []).entries()) {
    const at = "artists[" + index + "]";
    if (!artist || typeof artist !== "object" || Array.isArray(artist)) { fail(at + ": expected an object."); continue; }
    const allowed = ["id","name","danbooru_id","danbooru_name","aliases","category","tags","score","note","post_count","preview_urls","added_at","updated_at","featured","danbooru_url","danbooru_verified_at","preview_post_ids","preview_updated_at"];
    if (Object.keys(artist).some(key => !allowed.includes(key))) fail(at + ": unexpected property.");
    for (const key of ["id", "name", "danbooru_id", "danbooru_name", "category", "note"]) {
      if (typeof artist[key] !== "string" || (["id", "name", "danbooru_id", "danbooru_name", "category"].includes(key) && !artist[key].trim())) fail(at + "." + key + ": expected a non-empty string.");
    }
    const id = String(artist.id ?? "");
    if (ids.has(id)) fail(at + ": duplicate record id " + id + ".");
    ids.add(id);
    const dbid = String(artist.danbooru_id ?? "");
    if (!/^[0-9]+$/.test(dbid) || Number(dbid) <= 0) fail(at + ".danbooru_id: expected a positive numeric Danbooru Artist ID.");
    if (danbooruIds.has(dbid)) fail(at + ": duplicate Danbooru Artist ID " + dbid + ".");
    danbooruIds.add(dbid);
    if (!Array.isArray(artist.aliases) || artist.aliases.some(x => typeof x !== "string" || !x.trim())) fail(at + ".aliases: expected an array of non-empty strings.");
    else if (new Set(artist.aliases).size !== artist.aliases.length) fail(at + ".aliases: duplicate aliases are not allowed.");
    if (!Array.isArray(artist.tags) || artist.tags.some(x => typeof x !== "string" || !x.trim())) fail(at + ".tags: expected an array of non-empty strings.");
    if (artist.score !== null && (typeof artist.score !== "number" || artist.score < 1 || artist.score > 10)) fail(at + ".score: expected null or a number from 1 to 10.");
    if (!Number.isInteger(artist.post_count) || artist.post_count < 0) fail(at + ".post_count: expected a non-negative integer.");
    if (typeof artist.featured !== "boolean") fail(at + ".featured: expected a boolean.");
    if (!isDate(artist.added_at) || !isDate(artist.updated_at)) fail(at + ": added_at and updated_at must be ISO date-times.");
    if (!Array.isArray(artist.preview_urls) || artist.preview_urls.length > 12) fail(at + ".preview_urls: expected an array with at most 12 URLs.");
    if (artist.preview_post_ids !== undefined && (!Array.isArray(artist.preview_post_ids) || artist.preview_post_ids.length > 12)) fail(at + ".preview_post_ids: expected at most 12 post IDs.");
    if (artist.danbooru_url !== undefined) { try { const u = new URL(artist.danbooru_url); if (u.protocol !== "https:" || u.hostname !== "danbooru.donmai.us" || u.pathname !== "/artists/" + dbid) fail(at + ".danbooru_url: must point to this Danbooru Artist ID."); } catch { fail(at + ".danbooru_url: invalid URL."); } }
    if (artist.danbooru_verified_at !== undefined && !isDate(artist.danbooru_verified_at)) fail(at + ".danbooru_verified_at: invalid date-time.");
    if (artist.preview_updated_at !== undefined && !isDate(artist.preview_updated_at)) fail(at + ".preview_updated_at: invalid date-time.");
    for (const raw of Array.isArray(artist.preview_urls) ? artist.preview_urls : []) {
      try {
        const url = new URL(raw);
        if (url.protocol !== "https:" || !(url.hostname === "donmai.us" || url.hostname.endsWith(".donmai.us"))) fail(at + ".preview_urls: URL host is not an approved HTTPS Danbooru host: " + raw);
      } catch { fail(at + ".preview_urls: invalid URL " + raw + "."); }
    }
    for (const term of [artist.name, ...(Array.isArray(artist.aliases) ? artist.aliases : [])]) {
      const key = normalize(term);
      if (!key) continue;
      if (aliases.has(key) && aliases.get(key) !== dbid) warnings.push("Alias/name collision " + term + " between Danbooru IDs " + aliases.get(key) + " and " + dbid + "; review manually.");
      else aliases.set(key, dbid);
    }
  }
}

const htmlPath = path.join(root, "docs", "index.html");
if (fs.existsSync(htmlPath)) {
  const html = fs.readFileSync(htmlPath, "utf8");
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  const seen = new Set();
  for (const id of ids) { if (seen.has(id)) fail("docs/index.html: duplicate DOM id " + id + "."); seen.add(id); }
  const script = html.match(/<script>([\s\S]*?)<\/script>/i)?.[1];
  if (!script) fail("docs/index.html: inline application script was not found.");
  else {
    try { new Function(script); } catch (error) { fail("docs/index.html: JavaScript syntax error — " + error.message); }
    const refs = [...script.matchAll(/\$\("([^"]+)"\)/g)].map(match => match[1]);
    for (const id of new Set(refs)) if (!seen.has(id)) fail("docs/index.html: script references missing element #" + id + ".");
  }
} else fail("docs/index.html: file is missing.");

for (const warning of warnings) console.warn("WARN  " + warning);
for (const error of errors) console.error("FAIL  " + error);
if (errors.length) {
  console.error("\nCatalogue validation failed: " + errors.length + " error(s), " + warnings.length + " warning(s).");
  process.exitCode = 1;
} else {
  console.log("Catalogue validation passed: " + data.artists.length + " artist(s), " + warnings.length + " warning(s).");
}
