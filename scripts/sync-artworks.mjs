import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import os from "node:os";
import process from "node:process";
import { execFile } from "node:child_process";

const ROOT = process.cwd();
const ARTISTS_FILE = path.join(ROOT, "data", "artists.json");
const MANIFEST_FILE = path.join(ROOT, "data", "artworks.json");
const ASSET_ROOT = path.join(ROOT, "docs", "assets", "artists");
const USER_AGENT = "ArtistAtlasArtworkSync/1.0 (+https://github.com/Tera-Dark/artist-atlas)";
const MAX_IMAGE_BYTES = 32 * 1024 * 1024;
const MAX_TOTAL_BYTES = 180 * 1024 * 1024;
// Each archived master also gets a WebP display derivative. Reserve headroom so
// the combined budget checked by validate-artworks.mjs cannot be exceeded.
const DISPLAY_BUDGET_ALLOWANCE = 1 * 1024 * 1024;
const POST_LIMIT = 120;
const PER_ARTIST_DELAY_MS = 1200;
const PER_POST_DELAY_MS = 300;
// Two works whose 8x8 difference hash is within this Hamming distance are
// treated as variants (差分) of the same picture and never share a card.
const VARIANT_HASH_DISTANCE = 12;
const PREVIEW_CACHE_DIR = path.join(os.tmpdir(), "artist-atlas-preview-cache");
const PYTHON_BIN = process.platform === "win32" ? "python" : "python3";
const ALLOWED_EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp", "avif"]);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const isoNow = () => new Date().toISOString();

function fail(message) {
  throw new Error(message);
}

async function readJson(file) {
  try {
    return JSON.parse(await fs.readFile(file, "utf8"));
  } catch (error) {
    fail("Unable to read " + path.relative(ROOT, file) + ": " + error.message);
  }
}

function safeDanbooruTag(artist) {
  return String(artist.danbooru_name || artist.name || "").trim().replace(/\s+/g, "_");
}

function isAllowedImagePost(post) {
  const ext = String(post.file_ext || "").toLowerCase().replace(/^\./, "");
  return post.rating === "g" &&
    !post.is_deleted &&
    ALLOWED_EXTENSIONS.has(ext) &&
    Number(post.image_width) > 0 &&
    Number(post.image_height) > 0 &&
    Boolean(post.file_url || post.large_file_url);
}

async function fetchPopularPosts(artist) {
  const tag = safeDanbooruTag(artist);
  if (!tag) fail("Artist " + artist.id + " has no Danbooru tag.");
  const query = new URLSearchParams({
    tags: tag + " rating:g order:score",
    limit: String(POST_LIMIT),
    only: [
      "id", "rating", "score", "fav_count", "parent_id", "has_children",
      "file_url", "large_file_url", "preview_file_url",
      "file_ext", "file_size", "image_width", "image_height",
      "created_at", "is_deleted"
    ].join(",")
  });
  const response = await fetch("https://danbooru.donmai.us/posts.json?" + query.toString(), {
    headers: {
      "Accept": "application/json",
      "User-Agent": USER_AGENT
    },
    redirect: "follow"
  });
  if (!response.ok) {
    fail("Danbooru returned HTTP " + response.status + " for " + tag);
  }
  const posts = await response.json();
  if (!Array.isArray(posts)) fail("Danbooru returned an unexpected post list for " + tag);
  return posts
    .filter(isAllowedImagePost)
    .sort(function (a, b) {
      return (Number(b.score) || 0) - (Number(a.score) || 0) ||
        (Number(b.fav_count) || 0) - (Number(a.fav_count) || 0) ||
        Number(b.id) - Number(a.id);
    });
}

/* Danbooru records alternate costumes and small edits as child posts of the
   same parent. Walking that relation up to three levels catches most 差分
   without downloading anything. */
function isVariantFamily(candidate, selected, postsById) {
  if (Number(candidate.id) === Number(selected.id)) return true;
  if (candidate.parent_id && selected.parent_id &&
      Number(candidate.parent_id) === Number(selected.parent_id)) return true;
  if (Number(candidate.parent_id) === Number(selected.id)) return true;
  if (Number(selected.parent_id) === Number(candidate.id)) return true;
  for (const [anchor, other] of [[candidate, selected], [selected, candidate]]) {
    let node = anchor.parent_id ? postsById.get(Number(anchor.parent_id)) : null;
    for (let depth = 0; node && depth < 3; depth += 1) {
      if (Number(node.id) === Number(other.id)) return true;
      node = node.parent_id ? postsById.get(Number(node.parent_id)) : null;
    }
  }
  return false;
}

function hammingDistance(a, b) {
  if (!a || !b || a.length !== b.length) return Number.POSITIVE_INFINITY;
  let distance = 0;
  for (let index = 0; index < a.length; index += 1) {
    let value = parseInt(a[index], 16) ^ parseInt(b[index], 16);
    while (value) {
      distance += value & 1;
      value >>= 1;
    }
  }
  return distance;
}

function runPython(args) {
  return new Promise(function (resolve, reject) {
    execFile(PYTHON_BIN, args, { cwd: ROOT, timeout: 60000 }, function (error, stdout, stderr) {
      if (error) {
        reject(new Error(String(stderr || error.message).trim()));
        return;
      }
      resolve(String(stdout));
    });
  });
}

/* Perceptual signature of the 180x180 preview. The preview is only used for
   comparison and is never committed. */
async function previewSignature(artist, post) {
  if (!post.preview_file_url) return null;
  const dir = path.join(PREVIEW_CACHE_DIR, String(artist.danbooru_id));
  const file = path.join(dir, String(post.id) + ".img");
  try {
    await fs.mkdir(dir, { recursive: true });
    const downloaded = await downloadUrl(post.preview_file_url, "preview");
    await fs.writeFile(file, downloaded.bytes);
    const output = JSON.parse(await runPython(["scripts/image-signature.py", file]));
    const record = Array.isArray(output) ? output[0] : null;
    return record && typeof record.hash === "string" && record.hash.length === 16 ? record.hash : null;
  } catch (error) {
    console.warn("  preview signature unavailable for #" + post.id + ": " + error.message);
    return null;
  }
}

/* Alias names and the number of Danbooru posts help users judge how strongly a
   style is represented in the index. Missing values must not block archiving. */
async function fetchArtistFacts(artist) {
  const tag = safeDanbooruTag(artist);
  const facts = { name: null, aliases: null, post_count: null };
  try {
    const response = await fetch("https://danbooru.donmai.us/artists/" + artist.danbooru_id + ".json", {
      headers: { "Accept": "application/json", "User-Agent": USER_AGENT },
      redirect: "follow"
    });
    if (response.ok) {
      const data = await response.json();
      if (data && typeof data.name === "string") facts.name = data.name;
      if (Array.isArray(data?.other_names)) {
        facts.aliases = data.other_names.filter(function (value) {
          return typeof value === "string" && value.trim();
        });
      }
    }
  } catch (error) {
    console.warn("  artist profile unavailable for #" + artist.danbooru_id + ": " + error.message);
  }
  await sleep(PER_POST_DELAY_MS);
  try {
    const query = new URLSearchParams({ "search[name]": tag, limit: "1" });
    const response = await fetch("https://danbooru.donmai.us/tags.json?" + query.toString(), {
      headers: { "Accept": "application/json", "User-Agent": USER_AGENT },
      redirect: "follow"
    });
    if (response.ok) {
      const rows = await response.json();
      const row = Array.isArray(rows) ? rows[0] : null;
      if (row && Number.isFinite(Number(row.post_count))) facts.post_count = Number(row.post_count);
    }
  } catch (error) {
    console.warn("  tag statistics unavailable for " + tag + ": " + error.message);
  }
  return facts;
}

async function selectDistinctPosts(artist, posts) {
  const postsById = new Map(posts.map(function (post) { return [Number(post.id), post]; }));
  const chosen = [];
  const skipped = [];
  for (const post of posts) {
    if (chosen.length >= 3) break;
    const familyMatch = chosen.find(function (entry) {
      return isVariantFamily(post, entry.post, postsById);
    });
    if (familyMatch) {
      skipped.push({ post_id: Number(post.id), score: Number(post.score) || 0, reason: "variant_of_" + familyMatch.post.id });
      continue;
    }
    if (chosen.length > 0) await sleep(PER_POST_DELAY_MS);
    const hash = await previewSignature(artist, post);
    if (hash) {
      const similar = chosen.find(function (entry) {
        return entry.hash && hammingDistance(entry.hash, hash) <= VARIANT_HASH_DISTANCE;
      });
      if (similar) {
        skipped.push({ post_id: Number(post.id), score: Number(post.score) || 0, reason: "similar_to_" + similar.post.id });
        continue;
      }
    }
    chosen.push({ post, hash });
  }
  return { chosen, skipped };
}

function detectImage(buffer) {
  if (buffer.length >= 8 &&
      buffer.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
    return { ext: "png", mime: "image/png" };
  }
  if (buffer.length >= 3 && buffer[0] === 0xff && buffer[1] === 0xd8 && buffer[2] === 0xff) {
    return { ext: "jpg", mime: "image/jpeg" };
  }
  if (buffer.length >= 6 &&
      (buffer.subarray(0, 6).toString("ascii") === "GIF87a" ||
       buffer.subarray(0, 6).toString("ascii") === "GIF89a")) {
    return { ext: "gif", mime: "image/gif" };
  }
  if (buffer.length >= 12 &&
      buffer.subarray(0, 4).toString("ascii") === "RIFF" &&
      buffer.subarray(8, 12).toString("ascii") === "WEBP") {
    return { ext: "webp", mime: "image/webp" };
  }
  if (buffer.length >= 12 &&
      buffer.subarray(4, 8).toString("ascii") === "ftyp" &&
      /avif|avis/.test(buffer.subarray(8, 16).toString("ascii"))) {
    return { ext: "avif", mime: "image/avif" };
  }
  fail("Downloaded file is not a supported raster image.");
}

function isDanbooruHost(rawUrl) {
  try {
    const url = new URL(rawUrl);
    return url.protocol === "https:" &&
      (url.hostname === "donmai.us" || url.hostname.endsWith(".donmai.us"));
  } catch {
    return false;
  }
}

async function downloadUrl(rawUrl, variant) {
  if (!rawUrl || !isDanbooruHost(rawUrl)) {
    fail("Rejected non-Danbooru media URL.");
  }
  const response = await fetch(rawUrl, {
    headers: {
      "User-Agent": USER_AGENT,
      "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
    },
    redirect: "follow"
  });
  if (!response.ok) {
    fail("Media download returned HTTP " + response.status);
  }
  const declaredLength = Number(response.headers.get("content-length") || 0);
  if (declaredLength > MAX_IMAGE_BYTES) {
    fail("Image exceeds the per-file size limit (" + declaredLength + " bytes).");
  }
  const bytes = Buffer.from(await response.arrayBuffer());
  if (!bytes.length || bytes.length > MAX_IMAGE_BYTES) {
    fail("Downloaded image is empty or exceeds the per-file size limit.");
  }
  const image = detectImage(bytes);
  const declaredType = (response.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
  if (declaredType && !declaredType.startsWith("image/") && declaredType !== "application/octet-stream") {
    fail("Unexpected media content type: " + declaredType);
  }
  return {
    bytes,
    ext: image.ext,
    mime: image.mime,
    variant,
    final_url: response.url || rawUrl
  };
}

async function downloadPost(post) {
  const candidates = [];
  if (post.file_url) candidates.push({ url: post.file_url, variant: "original" });
  if (post.large_file_url && post.large_file_url !== post.file_url) {
    candidates.push({ url: post.large_file_url, variant: "large_sample" });
  }
  const errors = [];
  for (const candidate of candidates) {
    try {
      return await downloadUrl(candidate.url, candidate.variant);
    } catch (error) {
      errors.push(candidate.variant + ": " + error.message);
    }
  }
  fail("Post #" + post.id + " could not be downloaded: " + errors.join(" | "));
}

function sha256(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

async function removeStaleAssets(expectedByArtist) {
  await fs.mkdir(ASSET_ROOT, { recursive: true });
  const activeArtistIds = new Set(expectedByArtist.keys());
  for (const entry of await fs.readdir(ASSET_ROOT, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const dir = path.join(ASSET_ROOT, entry.name);
    const expected = expectedByArtist.get(entry.name) || new Set();
    if (!activeArtistIds.has(entry.name)) {
      await fs.rm(dir, { recursive: true, force: true });
      continue;
    }
    for (const file of await fs.readdir(dir)) {
      // Display derivatives are maintained by scripts/make-display-assets.py so
      // an unchanged master does not get re-encoded on every sync.
      if (file.endsWith(".display.webp")) continue;
      if (!expected.has(file)) await fs.rm(path.join(dir, file), { force: true });
    }
  }
}

function carryDisplayFields(previous, digest) {
  if (!previous || previous.sha256 !== digest || previous.display_source_sha256 !== digest) return {};
  if (!previous.display_url || !previous.display_file_size || !previous.display_sha256) return {};
  return {
    display_url: previous.display_url,
    display_variant: previous.display_variant,
    display_mime_type: previous.display_mime_type,
    display_width: previous.display_width,
    display_height: previous.display_height,
    display_file_size: previous.display_file_size,
    display_sha256: previous.display_sha256,
    display_source_sha256: previous.display_source_sha256,
    display_generated_at: previous.display_generated_at
  };
}

async function main() {
  const catalogue = await readJson(ARTISTS_FILE);
  if (!Array.isArray(catalogue.artists) || catalogue.artists.length === 0) {
    fail("The canonical artist catalogue is empty.");
  }

  const confirmedAt = "2026-11-17T02:44:26.000Z";
  const archivedArtists = [];
  const filesToWrite = [];
  let totalBytes = 0;
  let masterBytes = 0;

  // Keep existing display derivatives when the archived master is unchanged.
  const previousDisplay = new Map();
  try {
    const previous = JSON.parse(await fs.readFile(MANIFEST_FILE, "utf8"));
    for (const record of previous.artists || []) {
      for (const work of record.artworks || []) {
        if (work && work.post_id && work.display_url) previousDisplay.set(String(work.post_id), work);
      }
    }
  } catch {
    // No previous manifest yet: the display generator will create everything.
  }

  for (let artistIndex = 0; artistIndex < catalogue.artists.length; artistIndex += 1) {
    const artist = catalogue.artists[artistIndex];
    if (!/^\d+$/.test(String(artist.danbooru_id))) {
      fail("Invalid Danbooru Artist ID for " + artist.name);
    }
    if (artistIndex > 0) await sleep(PER_ARTIST_DELAY_MS);

    console.log("Discovering top-scoring General image posts for " + artist.name + " (#" + artist.danbooru_id + ")...");
    const posts = await fetchPopularPosts(artist);
    const facts = await fetchArtistFacts(artist);
    if (posts.length < 3) {
      fail("Only " + posts.length + " eligible General image posts found for " + artist.name + "; 3 are required.");
    }
    const selection = await selectDistinctPosts(artist, posts);
    const picked = selection.chosen.map(function (entry) { return entry.post; });
    if (picked.length < 3) {
      fail("Only " + picked.length + " distinct General image posts found for " + artist.name +
        " after variant filtering; 3 are required.");
    }
    if (selection.skipped.length) {
      console.log("  skipped " + selection.skipped.map(function (item) {
        return "#" + item.post_id + " (" + item.reason + ")";
      }).join(", "));
    }

    const artworks = [];
    for (const post of picked) {
      if (artworks.length > 0) await sleep(PER_POST_DELAY_MS);

      let downloaded;
      try {
        downloaded = await downloadPost(post);
      } catch (error) {
        console.warn("Skipping post #" + post.id + ": " + error.message);
        continue;
      }

      masterBytes += downloaded.bytes.length;
      totalBytes += downloaded.bytes.length + DISPLAY_BUDGET_ALLOWANCE;
      if (totalBytes > MAX_TOTAL_BYTES) {
        fail("The archive plus display derivatives would exceed the total repository image budget of " +
          Math.round(MAX_TOTAL_BYTES / 1024 / 1024) + " MiB.");
      }

      const filename = String(post.id) + "." + downloaded.ext;
      const assetPath = "assets/artists/" + artist.danbooru_id + "/" + filename;
      const outputPath = path.join(ROOT, "docs", ...assetPath.split("/"));
      filesToWrite.push({ outputPath, assetPath, filename, bytes: downloaded.bytes });
      const digest = sha256(downloaded.bytes);

      artworks.push({
        post_id: Number(post.id),
        source_url: "https://danbooru.donmai.us/posts/" + Number(post.id),
        source_file_url: post.file_url || post.large_file_url,
        local_url: assetPath,
        file_name: filename,
        file_ext: downloaded.ext,
        mime_type: downloaded.mime,
        image_width: Number(post.image_width),
        image_height: Number(post.image_height),
        file_size: downloaded.bytes.length,
        sha256: digest,
        downloaded_variant: downloaded.variant,
        created_at: post.created_at || null,
        archived_at: isoNow(),
        score: Number.isFinite(Number(post.score)) ? Number(post.score) : null,
        fav_count: Number.isFinite(Number(post.fav_count)) ? Number(post.fav_count) : null,
        selection_rank: artworks.length + 1,
        attribution: {
          artist: artist.danbooru_name || artist.name,
          artist_id: String(artist.danbooru_id),
          source_platform: "Danbooru"
        },
        ...carryDisplayFields(previousDisplay.get(String(post.id)), digest)
      });
    }

    if (artworks.length !== 3) {
      fail("Only " + artworks.length + " images could be downloaded for " + artist.name + "; no partial archive will be committed.");
    }

    archivedArtists.push({
      artist_id: String(artist.danbooru_id),
      artist_record_id: artist.id,
      artist_name: artist.name,
      artist_tag: safeDanbooruTag(artist),
      danbooru_name: facts.name || safeDanbooruTag(artist),
      danbooru_post_count: facts.post_count,
      danbooru_aliases: facts.aliases || [],
      facts_updated_at: isoNow(),
      selection: "top_scored_general_posts_without_variants",
      selection_detail: {
        method: "Posts are ordered by Danbooru score; near-duplicate variants are skipped using parent/child post relations and an 8x8 difference hash of the 180px preview.",
        pool_size: posts.length,
        variant_threshold: VARIANT_HASH_DISTANCE,
        skipped_variants: selection.skipped
      },
      permission: {
        status: "granted",
        confirmed_by: "repository_owner",
        confirmation: "Repository owner confirmed that the authors have permitted these works to be saved, rehosted, and publicly displayed in this repository.",
        confirmed_at: confirmedAt
      },
      artworks
    });

    console.log("Prepared 3 images for " + artist.name + ".");
  }

  const expectedByArtist = new Map();
  for (const item of filesToWrite) {
    const dir = path.dirname(item.outputPath);
    await fs.mkdir(dir, { recursive: true });
    const tempPath = item.outputPath + ".tmp";
    await fs.writeFile(tempPath, item.bytes);
    await fs.rename(tempPath, item.outputPath);
    const id = item.assetPath.split("/")[2];
    if (!expectedByArtist.has(id)) expectedByArtist.set(id, new Set());
    expectedByArtist.get(id).add(item.filename);
  }

  await removeStaleAssets(expectedByArtist);

  const manifest = {
    version: 1,
    status: "ready",
    updated_at: isoNow(),
    selection_policy: "Top 3 eligible General raster image posts per artist ordered by Danbooru score, excluding near-duplicate variants detected through parent/child post relations and perceptual-hash similarity.",
    storage_policy: "Original files are preferred; the large sample is used only if the original exceeds the configured file size limit or cannot be downloaded.",
    artists: archivedArtists
  };
  await fs.writeFile(MANIFEST_FILE, JSON.stringify(manifest, null, 2) + "\n", "utf8");

  await fs.rm(PREVIEW_CACHE_DIR, { recursive: true, force: true }).catch(function () {});

  console.log("Artwork archive ready: " + archivedArtists.length + " artists, " +
    filesToWrite.length + " images, " + (masterBytes / 1024 / 1024).toFixed(2) + " MiB masters " +
    "(display derivatives are generated by scripts/make-display-assets.py).");
}

main().catch((error) => {
  console.error("Artwork synchronization failed:", error);
  process.exitCode = 1;
});
