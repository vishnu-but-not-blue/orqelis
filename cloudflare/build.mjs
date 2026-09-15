import {mkdir, cp, readFile, writeFile} from 'node:fs/promises';
await mkdir('public/static', {recursive:true});
await mkdir('generated', {recursive:true});
await cp('../app/static', 'public/static', {recursive:true});
const shell = await readFile('../app/templates/app.html','utf8');
await writeFile('generated/shell.mjs', `export default ${JSON.stringify(shell)};\n`);
console.log('Built static assets and application shell; no environment files copied.');
