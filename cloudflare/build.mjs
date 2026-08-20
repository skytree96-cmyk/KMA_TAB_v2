import { copyFile, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const currentDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(currentDir, "..");
const outputDir = join(currentDir, "dist");
const sourceHtml = join(projectRoot, "docs", "TAP_오픈페이지_와이어프레임_v1.html");
const sourceGuide = join(projectRoot, "docs", "TAP_사용설명서_v3.pdf");
const appBase = "https://kmatap.streamlit.app";
const guidePdfBase64Token = "__TAP_GUIDE_PDF_BASE64__";

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

const guideLinks = html.match(/<a\b[^>]*\bdata-guide-download\b/g) || [];
if (guideLinks.length !== 3) {
  throw new Error(`Expected 3 guide download links, found ${guideLinks.length}.`);
}
if ((html.match(new RegExp(guidePdfBase64Token, "g")) || []).length !== 1) {
  throw new Error("Expected exactly one guide PDF payload token.");
}
html = html.replace(guidePdfBase64Token, "");

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
    "/tap-user-guide.pdf",
    '  Content-Disposition: attachment; filename="TAP_user_guide_v3.pdf"',
    "  Content-Type: application/pdf",
    "",
  ].join("\n"),
  "utf8",
);

console.log("Cloudflare open page built: cloudflare/dist");
