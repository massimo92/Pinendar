import assert from 'node:assert/strict';

import { clampGenerationTimeLimit } from '../public/generation-utils.mjs';

assert.equal(clampGenerationTimeLimit('31'), 30);
assert.equal(clampGenerationTimeLimit('16'), 16);
assert.equal(clampGenerationTimeLimit('15'), 15);
assert.equal(clampGenerationTimeLimit('2'), 2);
assert.equal(clampGenerationTimeLimit('0'), 1);
assert.equal(clampGenerationTimeLimit(''), null);

console.log('generation time limit regression: ok');
