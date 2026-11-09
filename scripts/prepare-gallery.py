#!/usr/bin/env python3
"""Prepare and validate the latest gallery in a disposable Actions checkout.
On a normal push conflict, discard only runner-local work and convert latest
source again. Never rebase auto-generated deletions or force-push the branch.
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent


def git(*args, check=True):
    return subprocess.run(['git', *args], cwd=ROOT, check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def refresh():
    git('fetch', '--no-tags', 'origin', '+refs/heads/main:refs/remotes/origin/main')
    return git('rev-parse', 'origin/main').stdout.strip()


def digest_tree(directory):
    digest = hashlib.sha256()
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('Unexpected symlink in published output')
        if path.is_file():
            name = path.relative_to(directory).as_posix().encode('utf-8')
            digest.update(len(name).to_bytes(8, 'big'))
            digest.update(name)
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('This helper is for a disposable GitHub Actions checkout only.')
    output = Path(os.environ['GITHUB_OUTPUT'])
    # 3 attempts max. Branch protections/network failures stop without deploying.
    for attempt in range(3):
        refresh()
        git('reset', '--hard', 'origin/main')
        has_png = any(p.is_file() and p.suffix.lower() == '.png' for p in (ROOT / 'media').rglob('*'))
        if has_png:
            if importlib.util.find_spec('PIL') is None:
                subprocess.run([sys.executable, '-m', 'pip', 'install', '-r',
                                '.github/requirements-images.txt'], cwd=ROOT, check=True)
            subprocess.run([sys.executable, 'scripts/optimize-images.py'], cwd=ROOT, check=True)
        else:
            print('No PNG files: skipped converter installation and conversion.', flush=True)
        # Fail before committing if any CMS image reference is broken.
        subprocess.run(['node', 'scripts/build.mjs'], cwd=ROOT, check=True)
        git('add', '--', 'media', 'content')
        changes = git('diff', '--cached', '--quiet', check=False)
        if changes.returncode not in (0, 1):
            raise RuntimeError('Could not inspect conversion changes')
        if changes.returncode == 1:
            git('config', 'user.name', 'github-actions[bot]')
            git('config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
            git('commit', '-m', 'Convert PNG images to lossless WebP')
            pushed = git('push', 'origin', 'HEAD:main', check=False)
            if pushed.returncode:
                print('Push was rejected; retrying from current main.', flush=True)
                if attempt == 2:
                    raise RuntimeError('Could not save conversion after 3 attempts; nothing was force-pushed.\n' + pushed.stderr)
                time.sleep(2)
                continue
        commit = git('rev-parse', 'HEAD').stdout.strip()
        if refresh() != commit:
            print('A newer CMS save arrived; rebuilding that version.', flush=True)
            if attempt == 2:
                raise RuntimeError('CMS kept changing during all 3 attempts; next run will handle the latest save.')
            continue
        digest = digest_tree(ROOT / 'dist')
        with output.open('a', encoding='utf-8') as stream:
            stream.write('commit=' + commit + '\n')
            stream.write('digest=' + digest + '\n')
        print('Prepared current main. Site fingerprint: ' + digest, flush=True)
        return
    raise RuntimeError('Could not prepare a stable revision')


if __name__ == '__main__':
    main()
