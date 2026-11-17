import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";

const root = process.cwd();
const cataloguePath = path.join(root, "data", "artists.json");
const manifestPath = path.join(root, "data", "artworks.json");
const totalBudget = 120 * 1024 * 1024;
const errors = [];
const fail = (message) => errors.push(message);

// This script is an ES module; keep file reads asynchronous at the top level.
async function loadJson(file) {
  try {
    return JSON.parse(await fs.readFile(file, "utf8"));
  } catch (error) {
    fail(path.relative(root, file) + ": " + error.message);
    return null;
  }
}

function imageType(buffer) {
  if (buffer.length >= 8 && buffer.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) return "image/png";
  if (buffer.length >= 3 && buffer[0] === 0xff && buffer[1] === 0xd8 && buffer[2] === 0xff) return "image/jpeg";
  if (buffer.length >= 6 && ["GIF87a", "GIF89a"].includes(buffer.subarray(0, 6).toString("ascii"))) return "image/gif";
  if (buffer.length >= 12 && buffer.subarray(0, 4).toString("ascii") === "RIFF" && buffer.subarray(8, 12).toString("ascii") === "WEBP") return "image/webp";
  if (buffer.length >= 12 && buffer.subarray(4, 8).toString("ascii") === "ftyp" && /avif|avis/.test(buffer.subarray(8, 16).toString("ascii"))) return "image/avif";
  return null;
}

function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

function validDate(value) {
  return typeof value === "string" && !Number.isNaN(Date.parse(value));
}

async function main() {
  const catalogue = await loadJson(cataloguePath);
  const manifest = await loadJson(manifestPath);
  if (!catalogue || !Array.isArray(catalogue.artists)) fail("data/artists.json must contain an artists array.");
  if (!manifest || manifest.version !== 1 || !Array.isArray(manifest.artists)) fail("data/artworks.json must be version 1 with an artists array.");
  if (!catalogue || !manifest || !Array.isArray(catalogue.artists) || !Array.isArray(manifest.artists)) {
    process.exitCode = 1;
    for (const error of errors) console.error("FAIL " + error);
    return;
  }

  if (!validDate(manifest.updated_at)) fail("data/artworks.json: updated_at must be an ISO date-time.");
  if (typeof manifest.display_policy !== "string" || !manifest.display_policy.trim()) fail("data/artworks.json: display_policy must describe the web display derivative rule.");
  if (!validDate(manifest.display_updated_at)) fail("data/artworks.json: display_updated_at must be an ISO date-time.");
  if (manifest.status === "pending") {
    if (manifest.artists.length !== 0) fail("A pending archive must not contain partial artist records.");
    if (errors.length) {
      for (const error of errors) console.error("FAIL " + error);
      process.exitCode = 1;
    } else {
      console.log("Artwork archive validation passed: pending initial synchronization.");
    }
    return;
  }
  if (manifest.status !== "ready") fail("data/artworks.json: status must be pending or ready.");
  if (manifest.status !== "ready") {
    for (const error of errors) console.error("FAIL " + error);
    process.exitCode = 1;
    return;
  }

  const catalogueById = new Map(catalogue.artists.map((artist) => [String(artist.danbooru_id), artist]));
  const seenArtists = new Set();
  const seenPosts = new Set();
  let totalBytes = 0;

  if (manifest.artists.length !== catalogue.artists.length) {
    fail("Every canonical artist must have exactly one artwork archive record.");
  }

  for (const [index, record] of manifest.artists.entries()) {
    const at = "artists[" + index + "]";
    if (!record || typeof record !== "object") {
      fail(at + ": expected an object.");
      continue;
    }
    const artistId = String(record.artist_id || "");
    const artist = catalogueById.get(artistId);
    if (!artist) fail(at + ": artist_id " + artistId + " is not in the canonical catalogue.");
    if (seenArtists.has(artistId)) fail(at + ": duplicate artist_id " + artistId + ".");
    seenArtists.add(artistId);
    if (!artist || record.artist_record_id !== artist.id) fail(at + ": artist_record_id does not match the canonical record.");
    if (record.permission?.status !== "granted" || record.permission?.confirmed_by !== "repository_owner" || !validDate(record.permission?.confirmed_at)) {
      fail(at + ": an explicit repository-owner permission confirmation is required.");
    }
    if (!Array.isArray(record.artworks) || record.artworks.length !== 3) {
      fail(at + ": exactly 3 archived artworks are required.");
      continue;
    }

    const referenced = new Set();
    for (const [workIndex, work] of record.artworks.entries()) {
      const where = at + ".artworks[" + workIndex + "]";
      if (!work || typeof work !== "object") {
        fail(where + ": expected an object.");
        continue;
      }
      const postId = String(work.post_id || "");
      if (!/^\d+$/.test(postId)) fail(where + ": invalid post_id.");
      if (seenPosts.has(artistId + ":" + postId)) fail(where + ": duplicate post_id.");
      seenPosts.add(artistId + ":" + postId);
      if (work.source_url !== "https://danbooru.donmai.us/posts/" + postId) fail(where + ": source_url must point to the exact Danbooru post.");
      if (work.attribution?.artist_id !== artistId || !work.attribution?.artist) fail(where + ": missing artist attribution.");
      if (!Number.isInteger(work.image_width) || work.image_width <= 0 || !Number.isInteger(work.image_height) || work.image_height <= 0) {
        fail(where + ": invalid image dimensions.");
      }
      if (!validDate(work.archived_at)) fail(where + ": archived_at must be an ISO date-time.");

      // Provenance of the source file: it is not stored, only described.
      if (typeof work.source_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(work.source_sha256)) {
        fail(where + ": source_sha256 must be a 64 character hex digest.");
      }
      if (!Number.isInteger(work.source_file_size) || work.source_file_size <= 0) fail(where + ": invalid source_file_size.");
      if (!["jpg", "jpeg", "png", "webp"].includes(String(work.source_file_ext))) fail(where + ": unsupported source_file_ext.");
      if (!/^image\//.test(String(work.source_mime_type || ""))) fail(where + ": invalid source_mime_type.");

      const expectedPrefix = "assets/artists/" + artistId + "/";
      const displayPath = String(work.display_url || "");
      if (!displayPath) {
        fail(where + ": missing display_url.");
        continue;
      }
      if (!["derived_1600_webp"].includes(String(work.display_variant || ""))) fail(where + ": unsupported display_variant.");
      if (work.display_source_sha256 !== work.source_sha256) fail(where + ": display derivative is stale for the archived source.");
      if (!Number.isInteger(work.display_width) || work.display_width <= 0 || !Number.isInteger(work.display_height) || work.display_height <= 0) {
        fail(where + ": invalid display dimensions.");
      }
      if (!validDate(work.display_generated_at)) fail(where + ": display_generated_at must be an ISO date-time.");
      const normalizedDisplay = path.posix.normalize(displayPath);
      if (displayPath !== normalizedDisplay || displayPath.startsWith("/") || displayPath.includes("\\") || !displayPath.startsWith(expectedPrefix)) {
        fail(where + ": unsafe or unexpected display_url.");
        continue;
      }
      if (path.posix.basename(displayPath) !== postId + ".display.webp") fail(where + ": display file name must be <post_id>.display.webp.");
      const displayFile = path.join(root, "docs", ...displayPath.split("/"));
      let displayBytes;
      try {
        displayBytes = await fs.readFile(displayFile);
      } catch {
        fail(where + ": missing display image " + displayPath + ".");
        continue;
      }
      referenced.add(path.posix.basename(displayPath));
      totalBytes += displayBytes.length;
      if (displayBytes.length !== work.display_file_size) fail(where + ": display_file_size does not match the stored file.");
      if (displayBytes.length > 4 * 1024 * 1024) fail(where + ": display image exceeds the 4 MiB limit.");
      if (imageType(displayBytes) !== "image/webp" || work.display_mime_type !== "image/webp") fail(where + ": display image must be WebP.");
      if (sha256(displayBytes) !== work.display_sha256) fail(where + ": display SHA-256 checksum mismatch.");
    }

    // Only display derivatives may live next to each other; no source masters.
    const artistDir = path.join(root, "docs", "assets", "artists", artistId);
    let files = [];
    try {
      files = await fs.readdir(artistDir);
    } catch {
      fail(at + ": missing asset directory " + path.relative(root, artistDir) + ".");
    }
    for (const file of files) {
      if (!referenced.has(file)) fail(at + ": unexpected file in asset directory: " + file);
    }
  }

  if (seenArtists.size !== catalogue.artists.length) fail("Not all canonical artists have an artwork archive record.");
  if (totalBytes > totalBudget) {
    fail("Artwork archive exceeds the " + Math.round(totalBudget / 1024 / 1024) + " MiB display budget.");
  }

  if (errors.length) {
    for (const error of errors) console.error("FAIL " + error);
    console.error("Artwork archive validation failed: " + errors.length + " error(s).");
    process.exitCode = 1;
  } else {
    console.log("Artwork archive validation passed: " + manifest.artists.length + " artists, " +
      manifest.artists.reduce((sum, item) => sum + item.artworks.length, 0) + " images, " +
      (totalBytes / 1024 / 1024).toFixed(2) + " MiB of display derivatives.");
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
