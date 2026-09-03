import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(scriptDir, "..");

const assets = [
  ["styles.css", "react/src/styles.css"],
  ["refinement.css", "react/src/refinement.css"],
];

const vendorAssets = [
  ["node_modules/react/umd/react.production.min.js", "react/public/vendor/react.production.min.js"],
  ["node_modules/react-dom/umd/react-dom.production.min.js", "react/public/vendor/react-dom.production.min.js"],
  ["node_modules/lucide-react/LICENSE", "react/public/licenses/lucide-react.txt"],
];

for (const [sourcePath, targetPath] of [...assets, ...vendorAssets]) {
  const source = resolve(frontendDir, sourcePath);
  const target = resolve(frontendDir, targetPath);
  mkdirSync(dirname(target), { recursive: true });
  copyFileSync(source, target);
  console.log(`Synced ${source} -> ${target}`);
}
