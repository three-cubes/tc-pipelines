import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';

test('generated-total', () => {
  const output = JSON.parse(readFileSync(new URL('./generated.json', import.meta.url)));
  assert.equal(output.total, 5, 'generated-total');
});
