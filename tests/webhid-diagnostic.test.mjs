import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { snapshotDevice } from '../experiments/phase-04b/webhid-diagnostic/snapshot.mjs';

test('recursive metadata includes child feature reports and excludes identifiers', () => {
  const selected = {
    vendorId: 0x258A, productId: 0x010C, productName: 'AULA F75',
    serialNumber: 'must-not-save', path: 'must-not-save',
    collections: [{
      usagePage: 0xFF00, usage: 1,
      inputReports: [{ reportId: 3 }], outputReports: [], featureReports: [{ reportId: 5 }],
      children: [{
        usagePage: 0xFF00, usage: 2,
        inputReports: [], outputReports: [{ reportId: 7 }],
        featureReports: [{ reportId: 6 }], children: [],
      }],
    }],
  };
  const result = snapshotDevice(selected);
  assert.equal(result.collections[0].children[0].featureReports[0], 6);
  assert.deepEqual(result.collections[0].outputReports, []);
  assert.deepEqual(result.collections[0].children[0].outputReports, [7]);
  assert.doesNotMatch(JSON.stringify(result), /must-not-save|serialNumber|path/);
});

test('diagnostic page has one filtered requestDevice and no report I/O', () => {
  const html = readFileSync(new URL('../experiments/phase-04b/webhid-diagnostic/index.html', import.meta.url), 'utf8');
  const module = readFileSync(new URL('../experiments/phase-04b/webhid-diagnostic/snapshot.mjs', import.meta.url), 'utf8');
  assert.match(html, /navigator\.hid\.requestDevice/);
  assert.match(html, /vendorId: 0x258A, productId: 0x010C/);
  for (const forbidden of ['.open(', '.sendFeatureReport(', '.receiveFeatureReport(', '.sendReport(']) {
    assert.equal(html.includes(forbidden) || module.includes(forbidden), false, forbidden);
  }
});
