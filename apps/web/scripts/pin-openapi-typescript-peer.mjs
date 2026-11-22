/* global process */
/**
 * openapi-typescript 7 imports TypeScript's TS 5 factory API. pnpm 11 resolves
 * its peer to the app's TS 7 even with a workspace override, so generation
 * fails with `ts.factory.createKeywordTypeNode is not a function`.
 *
 * This idempotent helper repoints only openapi-typescript's private peer
 * symlink to the TS 5.9.3 copy already present in the pnpm store. The app keeps
 * TS 7. Run it before `openapi-typescript` (see the `api:types` script).
 */
import { lstatSync, readdirSync, realpathSync, rmSync, symlinkSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const root = resolve(webDir, "..", "..");
const virtualStore = join(root, "node_modules", ".pnpm");

const storeEntries = readdirSync(virtualStore);
const ts5 = storeEntries.find((entry) => entry.startsWith("typescript@5."));
const generator = storeEntries.find((entry) => entry.startsWith("openapi-typescript@"));
if (!ts5 || !generator) {
  console.warn("TypeScript 5 or openapi-typescript is not installed; skipping peer pin.");
  process.exit(0);
}

const peer = join(virtualStore, generator, "node_modules", "typescript");
const target = join(virtualStore, ts5, "node_modules", "typescript");
let current = "";
try {
  current = realpathSync(peer);
} catch {
  // The peer link does not exist yet; it will be created below.
}
if (current === realpathSync(target)) {
  console.log(`openapi-typescript peer already pinned to ${ts5}`);
  process.exit(0);
}
if (current) {
  const stat = lstatSync(peer);
  if (!stat.isSymbolicLink()) {
    console.warn(`Refusing to replace non-symlink peer at ${peer}`);
    process.exit(0);
  }
  rmSync(peer);
}
symlinkSync(target, peer, "junction");
console.log(`Pinned openapi-typescript peer to ${ts5}`);
