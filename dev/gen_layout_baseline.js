'use strict';
// Writes tests/js/fixtures/unaccented-layout.json: a fingerprint of FTLayout.build() for every unaccented case in
// tests/js/unaccented.js. Run it ONLY with an engine whose unaccented layout is the one to keep (it was run once, on the
// engine of commit 0fa343e, before the accent headroom): `node dev/gen_layout_baseline.js`.
const fs = require('node:fs');
const path = require('node:path');
const { cases, hashOf } = require('../tests/js/unaccented.js');

const out = {};
cases().forEach(([key, take, s]) => { out[key] = hashOf(take, s); });
const file = path.join(__dirname, '..', 'tests', 'js', 'fixtures', 'unaccented-layout.json');
fs.writeFileSync(file, JSON.stringify(out, null, 0).replace(/,"/g, ',\n"') + '\n');
console.log('wrote', Object.keys(out).length, 'fingerprints to', file);
