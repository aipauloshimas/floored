'use strict';
// `node --test tests/js/` hands the folder to Node 22 as a file to run; this entry runs every *.test.js in it.
const fs = require('node:fs');
const path = require('node:path');
for (const f of fs.readdirSync(__dirname).sort()) if (f.endsWith('.test.js')) require(path.join(__dirname, f));
