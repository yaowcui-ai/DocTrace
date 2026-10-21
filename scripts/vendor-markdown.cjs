// Copy pinned browser dependencies locally; the app does not depend on a CDN.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const root = path.resolve(__dirname, '..');
const target = path.join(root, 'app/web/vendor');
fs.mkdirSync(target, {recursive:true});
const files = [
  ['marked', 'lib/marked.esm.js', 'marked.esm.js'],
  ['marked', 'LICENSE', 'marked.LICENSE'],
  ['dompurify', 'dist/purify.es.mjs', 'purify.es.mjs'],
  ['dompurify', 'LICENSE', 'dompurify.LICENSE'],
  ['dompurify', 'LICENSE-MPL', 'dompurify.LICENSE-MPL'],
];
const manifest = [];
for (const [name, sourceName, outputName] of files) {
  const packageRoot = path.join(root, 'node_modules', name);
  const metadata = JSON.parse(fs.readFileSync(path.join(packageRoot, 'package.json'), 'utf8'));
  const bytes = fs.readFileSync(path.join(packageRoot, sourceName));
  fs.writeFileSync(path.join(target, outputName), bytes);
  manifest.push({package:name, version:metadata.version, source:sourceName, file:outputName,
    sha256:crypto.createHash('sha256').update(bytes).digest('hex')});
}
fs.writeFileSync(path.join(target, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
console.log('Local Markdown libraries and licenses copied; SHA-256 manifest saved.');
