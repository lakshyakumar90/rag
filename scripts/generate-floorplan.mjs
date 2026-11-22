/** Regenerate the public map with a local checkout of haydenschmitty/floorplan. */
import { execFileSync } from "node:child_process";
import { copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const option = process.argv[2];
if (option === "--help" || process.argv.length !== 3) {
  console.log("Usage: node scripts/generate-floorplan.mjs <upstream checkout>/skills/floorplan");
  process.exit(option === "--help" ? 0 : 1);
}

const skill = path.resolve(option);
const root = fileURLToPath(new URL("../", import.meta.url));
const scratch = await mkdtemp(path.join(tmpdir(), "rag-floorplan-"));
const mapDir = path.join(scratch, "floorplan");
const input = path.join(root, "docs/floorplan/architecture.json");
const output = path.join(root, "apps/web/public/floorplan/index.html");

function run(command, args, cwd = scratch) {
  return execFileSync(command, args, {
    cwd, encoding: "utf8", windowsHide: true, maxBuffer: 32 * 1024 * 1024,
    env: { ...process.env, FLOORPLAN_UNATTENDED: "1" },
  });
}

try {
  // Work from tracked repository paths only. The scanner never sees local secrets
  // or workspace files, and its working directory is removed after export.
  const files = run("git", ["ls-files", "-z"], root).split("\0").filter(Boolean)
    .filter((file) => !file.startsWith("apps/web/public/floorplan/"));
  await Promise.all(files.map(async (file) => {
    const target = path.join(scratch, file);
    await mkdir(path.dirname(target), { recursive: true });
    await copyFile(path.join(root, file), target);
  }));
  run("git", ["init", "--quiet"]);
  run("git", ["-c", "core.autocrlf=false", "add", "--", "."]);
  await mkdir(mapDir, { recursive: true });
  await copyFile(input, path.join(mapDir, "architecture.json"));

  for (const step of ["scan", "build"]) {
    const result = JSON.parse(run(process.execPath, [path.join(skill, "scripts", `${step}.mjs`), scratch, "--json"]));
    if (!result.ok) throw new Error(JSON.stringify(result));
  }

  const exportPath = path.join(scratch, "rag-floorplan.html");
  run(process.execPath, [path.join(mapDir, "serve.mjs"), "--export", exportPath, "--include", "flows,notes"]);
  const html = await readFile(exportPath, "utf8");
  if (!html.includes('"exported":') || html.includes(scratch.replaceAll("\\", "/")) || !html.includes('id="context"')) {
    throw new Error("Expected a public Floorplan export without a local checkout path.");
  }
  await mkdir(path.dirname(output), { recursive: true });
  const styled = html.replace("</head>", '<style>#context { display: none; } #svg { clip-path: inset(var(--hh, 64px) 0 0 0); }</style>\n</head>');
  await writeFile(output, styled);
  console.log("Published apps/web/public/floorplan/index.html");
} finally {
  await rm(scratch, { recursive: true, force: true });
}
