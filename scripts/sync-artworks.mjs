import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import process from "node:process";

const ROOT = process.cwd();
const ARTISTS_FILE = path.join(ROOT, "data", "artists.json");
const MANIFEST_FILE = path.join(ROOT, "data", "artworks.json");
const ASSET_ROOT = path.join(ROOT, "docs", "assets", "artists");
const USER_AGENT = "ArtistAtlasArtworkSync/1.0 (+https://github.com/Tera-Dark/artist-atlas)";
const MAX_IMAGE_BYTES = 32 * 1024 * 1024;
const MAX_TOTAL_BYTES = 180 * 1024 * 1024;
const POST_LIMIT = 40;
const PER_ARTIST_DELAY_MS = 1200;
const PER_POST_DELAY_MS = 300;
const ALLOWED_EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp", "gif", "avif"]);

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

async function fetchLatestPosts(artist) {
  const tag = safeDanbooruTag(artist);
  if (!tag) fail("Artist " + artist.id + " has no Danbooru tag.");
  const query = new URLSearchParams({
    tags: tag + " rating:g order:id_desc",
    limit: String(POST_LIMIT),
    only: [
      "id", "rating", "file_url", "large_file_url", "preview_file_url",
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
    .sort((a, b) => Number(b.id) - Number(a.id));
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
      if (!expected.has(file)) await fs.rm(path.join(dir, file), { force: true });
    }
  }
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

  for (let artistIndex = 0; artistIndex < catalogue.artists.length; artistIndex += 1) {
    const artist = catalogue.artists[artistIndex];
    if (!/^\d+$/.test(String(artist.danbooru_id))) {
      fail("Invalid Danbooru Artist ID for " + artist.name);
    }
    if (artistIndex > 0) await sleep(PER_ARTIST_DELAY_MS);

    console.log("Discovering the newest General image posts for " + artist.name + " (#" + artist.danbooru_id + ")...");
    const posts = await fetchLatestPosts(artist);
    if (posts.length < 3) {
      fail("Only " + posts.length + " eligible General image posts found for " + artist.name + "; 3 are required.");
    }

    const artworks = [];
    for (const post of posts) {
      if (artworks.length >= 3) break;
      if (artworks.length > 0) await sleep(PER_POST_DELAY_MS);

      let downloaded;
      try {
        downloaded = await downloadPost(post);
      } catch (error) {
        console.warn("Skipping post #" + post.id + ": " + error.message);
        continue;
      }

      totalBytes += downloaded.bytes.length;
      if (totalBytes > MAX_TOTAL_BYTES) {
        fail("The selected archive exceeds the total repository image budget of " +
          Math.round(MAX_TOTAL_BYTES / 1024 / 1024) + " MiB.");
      }

      const filename = String(post.id) + "." + downloaded.ext;
      const assetPath = "assets/artists/" + artist.danbooru_id + "/" + filename;
      const outputPath = path.join(ROOT, "docs", ...assetPath.split("/"));
      filesToWrite.push({ outputPath, assetPath, filename, bytes: downloaded.bytes });

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
        sha256: sha256(downloaded.bytes),
        downloaded_variant: downloaded.variant,
        created_at: post.created_at || null,
        archived_at: isoNow(),
        attribution: {
          artist: artist.danbooru_name || artist.name,
          artist_id: String(artist.danbooru_id),
          source_platform: "Danbooru"
        }
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
      selection: "latest_general_posts",
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
    selection_policy: "Newest 3 non-deleted General raster image posts per artist, ordered by Danbooru post ID descending.",
    storage_policy: "Original files are preferred; the large sample is used only if the original exceeds the configured file size limit or cannot be downloaded.",
    artists: archivedArtists
  };
  await fs.writeFile(MANIFEST_FILE, JSON.stringify(manifest, null, 2) + "\n", "utf8");

  console.log("Artwork archive ready: " + archivedArtists.length + " artists, " +
    filesToWrite.length + " images, " + (totalBytes / 1024 / 1024).toFixed(2) + " MiB.");
}

main().catch((error) => {
  console.error("Artwork synchronization failed:", error);
  process.exitCode = 1;
});
