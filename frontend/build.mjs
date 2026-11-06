import { build } from 'esbuild'
import { readFile, readdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

const result = await build({
  entryPoints: ['frontend/editor.js', 'frontend/chapters.js'],
  bundle: true,
  minify: true,
  target: 'es2020',
  supported: { 'template-literal': false },
  outdir: 'alcove/static/alcove',
  metafile: true,
  banner: { js: '/*! Third-party licenses: editor.NOTICES.txt */' },
})

const packages = new Set()
for (const input of Object.keys(result.metafile.inputs)) {
  if (!input.startsWith('node_modules/')) continue
  const parts = input.split('/')
  packages.add(parts.slice(0, parts[1].startsWith('@') ? 3 : 2).join('/'))
}
const notices = []
for (const directory of [...packages].sort()) {
  const metadata = JSON.parse(await readFile(path.join(directory, 'package.json'), 'utf8'))
  const files = (await readdir(directory)).filter(name => /^licen[cs]e(?:\.|$)/i.test(name)).sort()
  if (!files.length) throw new Error(`Missing license for ${metadata.name}`)
  const licenses = await Promise.all(files.map(file => readFile(path.join(directory, file), 'utf8')))
  notices.push(`${metadata.name} ${metadata.version}\n${licenses.join('\n')}`)
}
await writeFile('alcove/static/alcove/editor.NOTICES.txt', notices.join('\n\n----\n\n'))
