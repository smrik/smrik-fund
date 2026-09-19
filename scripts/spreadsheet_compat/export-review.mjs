import { createHash } from 'node:crypto';
import { access, mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

import { buildAssetWorkbook, readSnapshot } from './asset_model.mjs';

const [, , modelArg, workbookArg, snapshotArg] = process.argv;
if (!modelArg || !workbookArg || !snapshotArg) throw new Error('usage: node export-review.mjs <model.json> <workbook.xlsx> <snapshot.json>');

const modelPath = resolve(modelArg);
const workbookPath = resolve(workbookArg);
const snapshotPath = resolve(snapshotArg);
if (workbookPath === snapshotPath) throw new Error('P11 workbook and snapshot paths must differ');

async function requireAbsent(path) {
  try {
    await access(path);
  } catch (error) {
    if (error?.code === 'ENOENT') return;
    throw error;
  }
  throw new Error(`P11 export refuses to overwrite: ${path}`);
}

const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const modelBytes = await readFile(modelPath);
const model = JSON.parse(modelBytes.toString('utf8').replace(/^\uFEFF/, ''));
await requireAbsent(workbookPath);
await requireAbsent(snapshotPath);
await mkdir(dirname(workbookPath), { recursive: true });
await mkdir(dirname(snapshotPath), { recursive: true });

const handle = await buildAssetWorkbook(model);
let snapshot;
try {
  snapshot = await readSnapshot(handle.wb);
  await handle.wb.save(workbookPath);
} finally {
  handle.wb.dispose();
}

const workbookSha256 = sha256(await readFile(workbookPath));
const result = {
  schemaVersion: 'p11-review-export-v1',
  annotatedModelSha256: sha256(modelBytes),
  selectedFinancialModelSha256: model.review_metadata?.bindings?.selected_model_sha256 ?? null,
  reviewId: model.review_metadata?.review?.id ?? null,
  reviewVersion: model.review_metadata?.review?.version ?? null,
  authoritativeVersion: model.review_metadata?.provenance?.authoritative_version ?? null,
  workbookSha256,
  snapshot,
};
await writeFile(snapshotPath, `${JSON.stringify(result, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
process.stdout.write(`${JSON.stringify({ workbookPath, snapshotPath, workbookSha256, reviewVersion: result.reviewVersion })}\n`);
