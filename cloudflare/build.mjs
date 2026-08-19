import { copyFile, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const currentDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(currentDir, "..");
const outputDir = join(currentDir, "dist");
const sourceHtml = join(projectRoot, "docs", "TAP_오픈페이지_와이어프레임_v1.html");
const sourceGuide = join(projectRoot, "docs", "TAP_사용설명서_v3.pdf");
const appBase = "https://kmatap.streamlit.app";

if (dirname(outputDir) !== currentDir || !outputDir.endsWith(join("cloudflare", "dist"))) {
  throw new Error("Unexpected Cloudflare output directory.");
}

let html = await readFile(sourceHtml, "utf8");
const appLinks = [
  `${appBase}/organization_report?tap_role=company`,
  `${appBase}/project_setup?tap_role=company`,
  `${appBase}/pre_assessment?tap_role=participant`,
  `${appBase}/post_assessment?tap_role=participant`,
  `${appBase}/kma_dashboard?tap_role=kma`,
];
for (const url of appLinks) {
  if (!html.includes(`href="${url}"`)) {
    throw new Error(`Expected app link was not found: ${url}`);
  }
}

const guideUrl = `${appBase}/user_guide?tap_role=company`;
if (!html.includes(`href="${guideUrl}"`)) {
  throw new Error(`Expected guide link was not found: ${guideUrl}`);
}
html = html.replaceAll(`href="${guideUrl}"`, 'href="/tap-user-guide.pdf"');

if (/github\.com\/skytree96-cmyk\/KMA_TAB_v2/i.test(html)) {
  throw new Error("The public page must not expose the GitHub repository link.");
}

await rm(outputDir, { recursive: true, force: true });
await mkdir(outputDir, { recursive: true });
await writeFile(join(outputDir, "index.html"), html, "utf8");
await copyFile(sourceGuide, join(outputDir, "tap-user-guide.pdf"));
await writeFile(
  join(outputDir, "_headers"),
  [
    "/*",
    "  X-Content-Type-Options: nosniff",
    "  Referrer-Policy: strict-origin-when-cross-origin",
    "  Permissions-Policy: camera=(), microphone=(), geolocation=()",
    "",
  ].join("\n"),
  "utf8",
);

console.log("Cloudflare open page built: cloudflare/dist");
