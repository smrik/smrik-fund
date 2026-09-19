import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { buildAssetWorkbook, combinedDecision } from './asset_model.mjs';

const p5Path = resolve('data/build-guide-p5/live-r3-20260906/model-input.json');
const p6Path = resolve('data/build-guide-p6/offline-r4/model-input.json');
const outputPath = resolve('data/build-guide-p6/offline-r4/state-proof-r4.json');
const HASH_FIELDS = ['candidate_hash', 'review_hash', 'context_hash', 'source_packet_hash'];

async function workbookState(model) {
  const handle = await buildAssetWorkbook(model);
  try {
    await handle.wb.calculate();
    const read = async (sheetName, address) => (await handle.wb.getSheet(sheetName)).getValue(address);
    const state = {
      headline: await read('Review', 'B3'),
      combined: await read('Decisions', 'B28'),
      p5: await read('Decisions', 'B4'),
      p6: await read('Decisions', 'B21'),
      dcf: await read('DCF', 'B24'),
    };
    const direct = combinedDecision(model);
    assert.equal(state.combined, direct.status, 'workbook combined status must equal JS summary predicate');
    return { ...state, direct: { status: direct.status, p5_binding_valid: direct.p5_binding_valid, p6_binding_valid: direct.p6_binding_valid } };
  } finally {
    handle.wb.dispose();
  }
}

function systemModel(base) {
  const model = structuredClone(base);
  const status = 'SYSTEM_REVIEWED_PROVISIONAL';
  model.p6_decision.status = status;
  model.operating_decision.status = status;
  model.operating_forecast.decision.status = status;
  return model;
}

function expected(status, p6, p5 = 'SYSTEM_REVIEWED_PROVISIONAL') {
  return { headline: status, combined: status, p5, p6, dcf: status };
}

async function runCase(name, model, expectedState, mutation, expectedBinding = null) {
  const actual = await workbookState(model);
  assert.deepEqual({ headline: actual.headline, combined: actual.combined, p5: actual.p5, p6: actual.p6, dcf: actual.dcf }, expectedState, `${name} state`);
  if (expectedBinding) assert.deepEqual({ p5_binding_valid: actual.direct.p5_binding_valid, p6_binding_valid: actual.direct.p6_binding_valid }, expectedBinding, `${name} binding predicate`);
  return { name, expected: expectedState, actual, pass: true, mutation: mutation ?? null };
}

const p5 = JSON.parse(await readFile(p5Path, 'utf8'));
const base = JSON.parse(await readFile(p6Path, 'utf8'));
const reviewed = systemModel(base);
const cases = [];
cases.push(await runCase('p5-standalone', structuredClone(p5), expected('UNREVIEWED_PROVISIONAL', 'MISSING'), null));
cases.push(await runCase('p6-offline-r4', structuredClone(base), expected('OFFLINE_FIXTURE', 'OFFLINE_FIXTURE'), null));
cases.push(await runCase('p6-system-reviewed-bound', structuredClone(reviewed), expected('SYSTEM_REVIEWED_PROVISIONAL', 'SYSTEM_REVIEWED_PROVISIONAL'), null));

const p5NoEvidence = structuredClone(reviewed);
delete p5NoEvidence.p5_decision.review_hashes;
cases.push(await runCase('p5-accepted-status-without-review-evidence', p5NoEvidence, expected('UNREVIEWED_PROVISIONAL', 'SYSTEM_REVIEWED_PROVISIONAL', 'UNREVIEWED_PROVISIONAL'), 'delete p5_decision.review_hashes', { p5_binding_valid: false, p6_binding_valid: true }));

const p6NoHashes = structuredClone(reviewed);
for (const field of HASH_FIELDS) delete p6NoHashes.p6_decision[field];
cases.push(await runCase('p6-accepted-status-without-binding-hashes', p6NoHashes, expected('UNREVIEWED_PROVISIONAL', 'UNREVIEWED_PROVISIONAL'), 'delete p6_decision binding hash fields', { p5_binding_valid: true, p6_binding_valid: false }));

const p6Mismatch = structuredClone(reviewed);
p6Mismatch.p6_decision.candidate_hash = 'mismatch';
cases.push(await runCase('p6-accepted-status-with-mismatched-binding-hashes', p6Mismatch, expected('UNREVIEWED_PROVISIONAL', 'UNREVIEWED_PROVISIONAL'), 'replace p6_decision.candidate_hash', { p5_binding_valid: true, p6_binding_valid: false }));

const p6CandidateDrift = structuredClone(reviewed);
p6CandidateDrift.operating_decision.proposal.segment_trajectories[0].stub_growth += 0.01;
cases.push(await runCase('p6-current-candidate-drift', p6CandidateDrift, expected('UNREVIEWED_PROVISIONAL', 'UNREVIEWED_PROVISIONAL'), 'change operating_decision.proposal.segment_trajectories[0].stub_growth', { p5_binding_valid: true, p6_binding_valid: false }));

const p6SourceDrift = structuredClone(reviewed);
p6SourceDrift.p6_decision.binding.source_case_snapshot_sha256 = 'old-source-context';
cases.push(await runCase('p6-review-bound-to-old-source-context', p6SourceDrift, expected('UNREVIEWED_PROVISIONAL', 'UNREVIEWED_PROVISIONAL'), 'replace p6_decision.binding.source_case_snapshot_sha256', { p5_binding_valid: true, p6_binding_valid: false }));

const stale = structuredClone(reviewed);
stale.p6_decision.stale = true;
cases.push(await runCase('p6-stale-flag', stale, expected('UNREVIEWED_PROVISIONAL', 'SYSTEM_REVIEWED_PROVISIONAL'), 'set p6_decision.stale=true'));

const rejected = structuredClone(reviewed);
rejected.p6_decision.status = 'REJECTED_BY_REVIEW';
rejected.operating_decision.status = 'REJECTED_BY_REVIEW';
rejected.operating_forecast.decision.status = 'REJECTED_BY_REVIEW';
cases.push(await runCase('p6-rejected', rejected, expected('REJECTED_BY_REVIEW', 'REJECTED_BY_REVIEW'), 'set P6 status REJECTED_BY_REVIEW'));

const missing = structuredClone(reviewed);
missing.p6_decision.status = 'P6_REVIEW_MISSING';
missing.operating_decision.status = 'P6_REVIEW_MISSING';
missing.operating_forecast.decision.status = 'P6_REVIEW_MISSING';
cases.push(await runCase('p6-missing', missing, expected('P6_REVIEW_MISSING', 'P6_REVIEW_MISSING'), 'set P6 status P6_REVIEW_MISSING'));

const output = {
  schema_version: 'p6-state-gate-r4-v1',
  status: 'PASS',
  scope: { p5: p5Path, p6: p6Path, engine: 'scripts/spreadsheet_compat/asset_model.mjs' },
  predicate: 'combinedDecision plus decisionRows require current P5/P6 hash records and candidate/review/source snapshots where present',
  counts: { cases: cases.length, passed: cases.filter((item) => item.pass).length },
  cases,
};
assert.equal(output.counts.passed, output.counts.cases, 'all R4 state cases must pass');
await mkdir(resolve(outputPath, '..'), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(output, null, 2)}\n`, 'utf8');
console.log(JSON.stringify({ status: output.status, output: outputPath, cases: output.counts }, null, 2));
