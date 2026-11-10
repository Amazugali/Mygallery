/**
 * Mygallery: read-only unused-media report.
 * Checks every text file in the repository (including unpublished content),
 * then lists media files that were never mentioned by path or filename.
 * It NEVER deletes, moves, or modifies any media or CMS content.
 * Run: node scripts/check-unused-media.mjs
 */
import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const mediaRoot = path.join(root, 'media');
const ignoredDirectories = new Set(['.git', 'node_modules', 'dist', '.next', '.cache', '.venv', 'coverage', '_site']);
const mediaExtensions = new Set(['.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif', '.svg', '.bmp', '.tif', '.tiff']);
const textExtensions = new Set(['.json', '.jsonc', '.html', '.htm', '.css', '.scss', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.md', '.mdx', '.txt', '.xml', '.yaml', '.yml', '.toml', '.svg']);
const maxTextBytes = 8 * 1024 * 1024;
const toPosix = p => p.split(path.sep).join('/');
const relative = p => toPosix(path.relative(root, p));

function walk(directory, shouldEnter = () => true) {
  if (!fs.existsSync(directory)) return [];
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      if (shouldEnter(entry.name, absolute)) files.push(...walk(absolute, shouldEnter));
    } else if (entry.isFile()) files.push(absolute);
  }
  return files;
}

if (!fs.existsSync(mediaRoot)) {
  console.error('media/ フォルダが見つかりません。Mygallery の一番上のフォルダから実行してください。');
  process.exitCode = 1;
} else {
  const mediaFiles = walk(mediaRoot).filter(file => mediaExtensions.has(path.extname(file).toLowerCase())).sort();
  const allTextFiles = walk(root, name => !ignoredDirectories.has(name) && name !== 'media')
    .filter(file => textExtensions.has(path.extname(file).toLowerCase()) || path.basename(file) === '.pages.yml');

  const textFiles = [];
  const skipped = [];
  for (const file of allTextFiles) {
    const size = fs.statSync(file).size;
    if (size > maxTextBytes) { skipped.push(relative(file)); continue; }
    try {
      const content = fs.readFileSync(file, 'utf8').toLowerCase();
      if (content.includes('\u0000')) { skipped.push(relative(file)); continue; }
      textFiles.push({ name: relative(file), content });
    } catch { skipped.push(relative(file)); }
  }

  // Conservative detection: a filename anywhere in source counts as "used",
  // including content of unpublished posts and hard-coded CSS/HTML references.
  // False positives are safe; false negatives can arise with dynamic paths.
  const unused = [];
  const used = [];
  for (const file of mediaFiles) {
    const repoPath = relative(file);
    const filename = path.basename(file);
    const needles = [repoPath.toLowerCase(), filename.toLowerCase(),
      encodeURI(repoPath).toLowerCase(), encodeURIComponent(filename).toLowerCase()];
    const matches = textFiles.filter(({ content }) => needles.some(needle => content.includes(needle)));
    const item = { path: repoPath, bytes: fs.statSync(file).size, references: matches.map(m => m.name) };
    (matches.length ? used : unused).push(item);
  }

  // Check explicit CMS image fields for broken references. This check includes
  // unpublished posts and catches paths still pointing to removed PNGs.
  const broken = [];
  const contentRoot = path.join(root, 'content');
  for (const file of walk(contentRoot).filter(file => file.endsWith('.json'))) {
    let data;
    try { data = JSON.parse(fs.readFileSync(file, 'utf8')); }
    catch (err) { broken.push(`${relative(file)}: JSONを読み取れません (${err.message})`); continue; }
    function inspect(value) {
      if (typeof value === 'string') {
        const match = value.trim().match(/^\/?(media\/[^?#]+)(?:[?#].*)?$/i);
        if (!match) return;
        let target = match[1];
        try { target = decodeURIComponent(target); } catch { /* keep original */ }
        const parts = target.replaceAll('\\', '/').split('/');
        if (parts.includes('..') || parts.includes('.')) {
          broken.push(`${relative(file)}: 不正な画像パス ${value}`); return;
        }
        const absolute = path.join(root, ...parts);
        if (!fs.existsSync(absolute) || !fs.statSync(absolute).isFile()) {
          broken.push(`${relative(file)}: ${value}`);
        }
      } else if (Array.isArray(value)) value.forEach(inspect);
      else if (value && typeof value === 'object') Object.values(value).forEach(inspect);
    }
    inspect(data);
  }

  const formatBytes = n => n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(2)} MB` : `${(n / 1024).toFixed(1)} KB`;
  const totalUnused = unused.reduce((sum, item) => sum + item.bytes, 0);
  const lines = [
    '# Mygallery 未使用画像チェック', '',
    `- media内の画像: **${mediaFiles.length}枚**`,
    `- 使用中と判定: **${used.length}枚**`,
    `- 未使用の可能性: **${unused.length}枚（${formatBytes(totalUnused)}）**`,
    `- 確認したテキストファイル: **${textFiles.length}件**`, '',
    '> **画像は一切削除していません。** 以下は削除候補です。画像パスをプログラムで組み立てている場合など、検出できない参照もあり得ます。削除前に目視確認してください。', '',
    '## 削除候補', ''
  ];
  if (unused.length === 0) lines.push('候補はありません。');
  else for (const item of unused) lines.push(`- \`${item.path.replaceAll('`', '\\`')}\` — ${formatBytes(item.bytes)}`);
  lines.push('', '## CMSデータ内の参照切れ', '');
  if (broken.length === 0) lines.push('検出されませんでした。');
  else {
    lines.push('**参照切れがあります。画像を削除する前に、こちらを修正してください。**', '');
    for (const issue of broken) lines.push(`- ${issue.replaceAll('`', '\\`')}`);
  }
  if (skipped.length) {
    lines.push('', '## 読み飛ばしたファイル', '',
      '下記はサイズ超過・読み取り失敗などで確認できませんでした。削除候補の判定は不完全です。', '');
    for (const file of skipped) lines.push(`- \`${file.replaceAll('`', '\\`')}\``);
  }
  lines.push('', '---',
    '※ 未公開投稿の画像も「使用中」として扱います。削除してもGitの過去の履歴にある画像は消えません。',
    '※ このチェックは静的な文字列参照を調べるものです。自動削除はしません。', '');

  const report = lines.join('\n');
  console.log(report);
  if (process.env.GITHUB_STEP_SUMMARY) {
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, report + '\n');
  }
  if (skipped.length) process.exitCode = 2;
}
