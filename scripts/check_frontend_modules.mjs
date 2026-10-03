// Static ESM parse + link check for the Sangam frontend.
// Uses V8's real module system (vm.SourceTextModule) WITHOUT evaluating any
// code, so the verdict matches what Chrome does at import time:
//   * syntax errors -> SyntaxError
//   * missing named exports -> LinkError ("does not provide an export named ...")
//
// Note: `node --check` alone is NOT enough — with Node 22+/24 it can report
// "OK" for files that fail as ES modules unless package.json declares
// "type": "module" (mainfiles/frontend/package.json does). This checker has no
// such blind spot: it parses and links every module through V8 itself.
//
// Run: node --experimental-vm-modules scripts/check_frontend_modules.mjs
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  'mainfiles',
  'frontend',
  'js',
);

function collectJsFiles(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...collectJsFiles(p));
    else if (e.name.endsWith('.js')) out.push(p);
  }
  return out;
}

const files = collectJsFiles(ROOT);
let bad = 0;

for (const entry of files) {
  const cache = new Map();
  const load = (file) => {
    if (cache.has(file)) return cache.get(file);
    const mod = new vm.SourceTextModule(fs.readFileSync(file, 'utf8'), { identifier: file });
    cache.set(file, mod);
    return mod;
  };
  const resolver = async (spec, referencingMod) => {
    if (!spec.startsWith('.')) throw new Error(`bare specifier '${spec}' (expected relative)`);
    const file = path.resolve(path.dirname(referencingMod.identifier), spec);
    const target = file.endsWith('.js') ? file : file + '.js';
    if (!fs.existsSync(target)) throw new Error(`missing file: ${spec} (from ${referencingMod.identifier})`);
    return load(target);
  };
  try {
    const entryMod = load(entry);
    await entryMod.link(resolver);
    console.log(`OK   ${path.relative(process.cwd(), entry)}`);
  } catch (e) {
    bad++;
    console.log(`FAIL ${path.relative(process.cwd(), entry)}\n     ${String(e.message || e).split('\n').slice(0, 3).join('\n     ')}`);
  }
}

console.log(bad === 0 ? `\nALL ${files.length} MODULES PARSE + LINK` : `\n${bad} MODULE(S) BROKEN`);
process.exit(bad === 0 ? 0 : 1);
