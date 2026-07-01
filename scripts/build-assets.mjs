import { watch } from "node:fs";
import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import autoprefixer from "autoprefixer";
import cssnano from "cssnano";
import postcss from "postcss";
import postcssImport from "postcss-import";
import tailwindcss from "@tailwindcss/postcss";

const require = createRequire(import.meta.url);
const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const frontendDir = path.join(rootDir, "frontend");
const buildDir = path.join(frontendDir, "build");
const sourceCssPath = path.join(frontendDir, "src", "styles", "index.css");
const outputCssPath = path.join(buildDir, "css", "index.css");
const sourceJsDir = path.join(frontendDir, "src", "js");
const outputJsDir = path.join(buildDir, "js");
const vendorSourceDir = path.join(frontendDir, "vendors");
const vendorOutputDir = path.join(buildDir, "vendors");
const watchMode = process.argv.includes("--watch");
const production = process.env.NODE_ENV === "production";

async function pathExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch (_error) {
    return false;
  }
}

async function cleanBuildDir() {
  await fs.rm(buildDir, { force: true, recursive: true });
  await fs.mkdir(buildDir, { recursive: true });
}

async function copyIfExists(source, destination) {
  if (!(await pathExists(source))) {
    return;
  }

  await fs.mkdir(path.dirname(destination), { recursive: true });
  await fs.copyFile(source, destination);
}

async function copyDirectoryIfExists(source, destination) {
  if (!(await pathExists(source))) {
    return;
  }

  await fs.cp(source, destination, { force: true, recursive: true });
}

async function buildCss() {
  const css = await fs.readFile(sourceCssPath, "utf8");
  const plugins = [postcssImport(), tailwindcss(), autoprefixer()];

  if (production) {
    plugins.push(cssnano());
  }

  const result = await postcss(plugins).process(css, {
    from: sourceCssPath,
    map: production ? false : { inline: false },
    to: outputCssPath,
  });

  await fs.mkdir(path.dirname(outputCssPath), { recursive: true });
  await fs.writeFile(outputCssPath, result.css, "utf8");

  if (result.map) {
    await fs.writeFile(`${outputCssPath}.map`, result.map.toString(), "utf8");
  }
}

async function copyScripts() {
  await copyDirectoryIfExists(sourceJsDir, outputJsDir);
}

async function copyVendorAssets() {
  await copyDirectoryIfExists(vendorSourceDir, vendorOutputDir);
  await copyIfExists(
    require.resolve("alpinejs/dist/cdn.min.js"),
    path.join(vendorOutputDir, "js", "alpine.min.js"),
  );
}

async function writeManifest() {
  const manifest = {
    "css/index.css": "/static/css/index.css",
    "js/alpine-components.js": "/static/js/alpine-components.js",
    "js/app.js": "/static/js/app.js",
    "vendors/js/alpine.min.js": "/static/vendors/js/alpine.min.js",
  };

  await fs.writeFile(path.join(buildDir, "manifest.json"), JSON.stringify(manifest, null, 2), "utf8");
}

async function build() {
  await cleanBuildDir();
  await Promise.all([buildCss(), copyScripts(), copyVendorAssets()]);
  await writeManifest();
  console.log(`Built frontend assets in ${path.relative(rootDir, buildDir)}`);
}

async function watchDirectory(directory, onChange, watchers = []) {
  if (!(await pathExists(directory))) {
    return watchers;
  }

  const entries = await fs.readdir(directory, { withFileTypes: true });
  const watcher = watch(directory, { persistent: true }, onChange);
  watchers.push(watcher);

  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name === "node_modules" || entry.name === "build") {
      continue;
    }

    await watchDirectory(path.join(directory, entry.name), onChange, watchers);
  }

  return watchers;
}

async function watchAssets() {
  let rebuildTimer = null;
  const scheduleRebuild = () => {
    if (rebuildTimer) {
      clearTimeout(rebuildTimer);
    }

    rebuildTimer = setTimeout(async () => {
      try {
        await build();
      } catch (error) {
        console.error(error);
      }
    }, 250);
  };

  await Promise.all(
    [
      path.join(frontendDir, "src"),
      path.join(frontendDir, "templates"),
      path.join(rootDir, "apps"),
      path.join(rootDir, "rowset"),
    ].map((directory) => watchDirectory(directory, scheduleRebuild)),
  );

  console.log("Watching frontend assets...");
}

await build();

if (watchMode) {
  await watchAssets();
  await new Promise(() => {});
}
