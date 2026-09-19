import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildAssetWorkbook, inspectAssetWorkbook, MODEL_VERSION, ENGINE_VERSION } from './asset_model.mjs';

const [, , command = 'build', inputArg, runArg] = process.argv;
const inputPath = resolve(inputArg ?? fileURLToPath(new URL('../../data/build-guide-p5/model-input.json', import.meta.url)));
const runDir = resolve(runArg ?? fileURLToPath(new URL('../../data/build-guide-p5/manual-run', import.meta.url)));
const workbookPath = resolve(runDir, 'asset-model.xlsx');
const verificationPath = resolve(runDir, 'asset-verification.json');
const rebuildPath = resolve(runDir, 'asset-rebuild-verification.json');

async function sha256(path) {
  return createHash('sha256').update(await readFile(path)).digest('hex');
}

async function saveWorkbook(path, model) {
  const handle = await buildAssetWorkbook(model);
  try {
    await handle.wb.save(path);
  } finally {
    handle.wb.dispose();
  }
}

async function build() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  await mkdir(runDir, { recursive: true });
  const attemptId = randomUUID();
  const candidatePath = resolve(runDir, `asset-candidate-${attemptId}.xlsx`);
  await saveWorkbook(candidatePath, model);
  const publishedHash = await sha256(candidatePath);
  const snapshot = await inspectAssetWorkbook(candidatePath);
  const modelHash = createHash('sha256').update(JSON.stringify(model)).digest('hex');
  const verification = {
    status: 'PASS',
    modelVersion: MODEL_VERSION,
    engineVersion: ENGINE_VERSION,
    inputPath,
    workbookPath,
    modelHash,
    publishedSha256: publishedHash,
    snapshot,
    checks: snapshot.checks,
  };
  const rebuiltPath = resolve(runDir, `asset-rebuild-${attemptId}.xlsx`);
  await saveWorkbook(rebuiltPath, model);
  const rebuiltSnapshot = await inspectAssetWorkbook(rebuiltPath);
  const rebuiltHash = await sha256(rebuiltPath);
  const rebuild = {
    status: JSON.stringify(snapshot) === JSON.stringify(rebuiltSnapshot) ? 'PASS' : 'FAIL',
    publishedSha256: publishedHash,
    rebuiltSha256: rebuiltHash,
    snapshot,
    rebuiltSnapshot,
  };
  if (rebuild.status !== 'PASS') throw new Error('Mog rebuild snapshot mismatch');
  // A failed construction, validation or rebuild never replaces a valid output.
  await rename(candidatePath, workbookPath);
  await writeFile(verificationPath, `${JSON.stringify(verification, null, 2)}\n`, 'utf8');
  await writeFile(rebuildPath, `${JSON.stringify(rebuild, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({ status: 'PASS', verificationPath, rebuildPath, snapshot }, null, 2));
}

async function inspect() {
  const snapshot = await inspectAssetWorkbook(workbookPath);
  console.log(JSON.stringify(snapshot, null, 2));
}

if (command === 'build') await build();
else if (command === 'inspect') await inspect();
else throw new Error(`Unknown P5 command: ${command}`);

// Mog workers can keep the Node event loop alive after all awaited work completes.
process.exit(0);
