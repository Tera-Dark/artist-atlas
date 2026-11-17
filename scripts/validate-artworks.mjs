import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";

const root = process.cwd();
const cataloguePath = path.join(root, "data", "artists.json");
const manifestPath = path.join(root, "data", "artworks.json");
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

      const assetPath = String(work.local_url || "");
      const expectedPrefix = "assets/artists/" + artistId + "/";
      const normalized = path.posix.normalize(assetPath);
      if (assetPath !== normalized || assetPath.startsWith("/") || assetPath.includes("\\") || !assetPath.startsWith(expectedPrefix)) {
        fail(where + ": unsafe or unexpected local_url.");
        continue;
      }
      const assetFile = path.join(root, "docs", ...assetPath.split("/"));
      let bytes;
      try {
        bytes = await fs.readFile(assetFile);
      } catch {
        fail(where + ": missing local image " + assetPath + ".");
        continue;
      }
      totalBytes += bytes.length;
      if (!bytes.length || bytes.length !== work.file_size) fail(where + ": file_size does not match the stored file.");
      if (bytes.length > 32 * 1024 * 1024) fail(where + ": image exceeds the 32 MiB per-file limit.");
      if (imageType(bytes) !== work.mime_type) fail(where + ": file signature does not match mime_type.");
      if (sha256(bytes) !== work.sha256) fail(where + ": SHA-256 checksum mismatch.");
      if (path.basename(assetPath) !== work.file_name) fail(where + ": file_name does not match local_url.");
    }
  }

  if (seenArtists.size !== catalogue.artists.length) fail("Not all canonical artists have an artwork archive record.");
  if (totalBytes > 180 * 1024 * 1024) fail("Artwork archive exceeds the 180 MiB total size budget.");

  if (errors.length) {
    for (const error of errors) console.error("FAIL " + error);
    console.error("Artwork archive validation failed: " + errors.length + " error(s).");
    process.exitCode = 1;
  } else {
    console.log("Artwork archive validation passed: " + manifest.artists.length + " artists, " +
      manifest.artists.reduce((sum, item) => sum + item.artworks.length, 0) + " images, " +
      (totalBytes / 1024 / 1024).toFixed(2) + " MiB.");
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
