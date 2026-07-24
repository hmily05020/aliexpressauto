const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const electronDist = path.join(root, "node_modules", "electron", "dist");
const releaseRoot = path.join(root, "release");
const appName = "店小秘自动编辑助手";
let outDir = path.join(releaseRoot, `${appName}-win-x64`);
let resourcesDir = path.join(outDir, "resources");
let appDir = path.join(resourcesDir, "app");

function copyDir(source, target) {
  fs.mkdirSync(target, { recursive: true });
  fs.cpSync(source, target, { recursive: true, force: true });
}

function removeIfExists(target) {
  if (fs.existsSync(target)) {
    fs.rmSync(target, { recursive: true, force: true });
  }
}

if (!fs.existsSync(path.join(electronDist, "electron.exe"))) {
  throw new Error("Electron runtime not found. Run npm install first.");
}

try {
  removeIfExists(outDir);
} catch (error) {
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "-");
  outDir = path.join(releaseRoot, `${appName}-win-x64-${stamp}`);
  resourcesDir = path.join(outDir, "resources");
  appDir = path.join(resourcesDir, "app");
  console.warn(`Default release folder is locked, packaging to: ${outDir}`);
}

fs.mkdirSync(appDir, { recursive: true });

copyDir(electronDist, outDir);
fs.renameSync(path.join(outDir, "electron.exe"), path.join(outDir, `${appName}.exe`));

copyDir(path.join(root, "dist"), path.join(appDir, "dist"));
copyDir(path.join(root, "electron"), path.join(appDir, "electron"));

const packageJson = {
  name: "aliexpress-dxm-assistant-desktop",
  version: "0.1.0",
  private: true,
  main: "electron/main.cjs"
};

fs.writeFileSync(path.join(appDir, "package.json"), `${JSON.stringify(packageJson, null, 2)}\n`, "utf8");

console.log(`Packaged Windows app: ${path.join(outDir, `${appName}.exe`)}`);
