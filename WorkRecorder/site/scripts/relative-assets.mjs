import { readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const distDir = new URL("../dist/", import.meta.url);

async function listHtml(dirUrl) {
  const entries = await readdir(dirUrl, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const child = new URL(entry.name, dirUrl);
    if (entry.isDirectory()) {
      files.push(...(await listHtml(new URL(`${entry.name}/`, dirUrl))));
      continue;
    }
    if (entry.isFile() && entry.name.endsWith(".html")) {
      files.push(child);
    }
  }
  return files;
}

for (const fileUrl of await listHtml(distDir)) {
  const path = fileUrl.pathname;
  const depth = path
    .replace(distDir.pathname, "")
    .split("/")
    .filter(Boolean).length - 1;
  const prefix = depth <= 0 ? "" : "../".repeat(depth);
  const html = await readFile(fileUrl, "utf8");
  const rewritten = html
    .replaceAll('href="/_astro/', `href="${prefix}_astro/`)
    .replaceAll('src="/_astro/', `src="${prefix}_astro/`);
  if (rewritten !== html) {
    await writeFile(fileUrl, rewritten);
  }
}

console.log(`Rewrote Astro asset URLs in ${join("site", "dist")}.`);
