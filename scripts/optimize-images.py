#!/usr/bin/env python3
"""Replace repository PNGs with smaller lossless WebP and update CMS JSON.
Run before building. Only media/ and content/**/*.json are modified.
Git history is never rewritten. Commit and push are owned by the workflow.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
IMAGE_FIELDS = {'avatar', 'banner', 'thumbnail', 'standing', 'settings', 'art', 'src', 'pages'}


def canonical(value):
    if not isinstance(value, str):
        return None
    value = value.lstrip('/')
    if not value.startswith('media/') or '..' in Path(value).parts:
        return None
    return value


def rewrite(value, mapping, image=False):
    if isinstance(value, dict):
        return {k: rewrite(v, mapping, k in IMAGE_FIELDS) for k, v in value.items()}
    if isinstance(value, list):
        return [rewrite(v, mapping, image) for v in value]
    path = canonical(value) if image else None
    if path in mapping:
        return ('/' if value.startswith('/') else '') + mapping[path]
    return value


def strings(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)
    elif isinstance(value, str):
        yield value


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(prefix='.webp-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main(root=ROOT):
    root = Path(root).resolve()
    media = root / 'media'
    content = root / 'content'
    if not media.is_dir() or not content.is_dir():
        raise ValueError('Run in a gallery repository with media/ and content/.')
    # Read everything first; invalid JSON aborts before any mutation.
    documents = {}
    for path in sorted(content.rglob('*.json')):
        if path.is_symlink() or not path.resolve().is_relative_to(content.resolve()):
            raise ValueError('Unexpected symbolic link in content/')
        documents[path] = json.loads(path.read_text(encoding='utf-8'))
    mapping, payloads = {}, {}
    before = sum(p.stat().st_size for p in media.rglob('*') if p.is_file())
    for path in sorted(media.rglob('*')):
        if not path.is_file() or path.suffix.lower() != '.png':
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(media.resolve()):
            raise ValueError('Unexpected symbolic link in media/')
        source = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != 'PNG' or getattr(image, 'n_frames', 1) != 1 or image.mode not in ('RGB', 'RGBA', 'P', 'L', 'LA'):
                    print('Kept original:', path.name, '(animated or special image)')
                    continue
                rgba = image.convert('RGBA')
                options = dict(format='WEBP', lossless=True, method=6, exact=True)
                if image.info.get('icc_profile'):
                    options['icc_profile'] = image.info['icc_profile']
                encoded = io.BytesIO()
                rgba.save(encoded, **options)
                encoded = encoded.getvalue()
                if len(encoded) >= len(raw):
                    continue
                with Image.open(io.BytesIO(encoded)) as decoded:
                    if decoded.size != rgba.size or decoded.convert('RGBA').tobytes() != rgba.tobytes():
                        raise ValueError('Lossless verification failed')
                digest = hashlib.sha256(encoded).hexdigest()
                target = 'media/_webp/' + digest + '.webp'
                mapping[source], payloads[target] = target, encoded
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            print('Kept original:', path.name, '(' + type(exc).__name__ + ')')
    # Do not delete PNGs referenced by unknown JSON fields or handwritten code.
    tentative = {p: rewrite(doc, mapping) for p, doc in documents.items()}
    blocked = {canonical(s) for doc in tentative.values() for s in strings(doc)} & mapping.keys()
    for directory in ('assets',):
        for path in (root / directory).rglob('*'):
            if path.is_file() and path.suffix.lower() in ('.html', '.js', '.css', '.json'):
                text = path.read_text(encoding='utf-8')
                blocked.update(source for source in mapping if source in text)
    if (root / 'index.html').exists():
        text = (root / 'index.html').read_text(encoding='utf-8')
        blocked.update(source for source in mapping if source in text)
    for source in blocked:
        del mapping[source]
        print('Kept original:', Path(source).name, '(reference outside supported image fields)')
    updated = {p: rewrite(doc, mapping) for p, doc in documents.items()}
    for target in set(mapping.values()):
        destination = root / target
        if destination.parent.is_symlink() or destination.is_symlink():
            raise ValueError('Unexpected symbolic link in WebP output')
        destination.parent.mkdir(parents=True, exist_ok=True)
        encoded = payloads[target]
        if destination.exists() and destination.read_bytes() != encoded:
            raise ValueError('Output collision; original files retained')
        destination.write_bytes(encoded)
    # Persist all references before deleting even one original PNG.
    for path, document in updated.items():
        if document != documents[path]:
            atomic_json(path, document)
    for source, target in mapping.items():
        if not (root / target).is_file():
            raise ValueError('Missing WebP output; originals retained')
        if any(canonical(s) == source for doc in updated.values() for s in strings(doc)):
            raise ValueError('PNG reference remains; originals retained')
    for source in mapping:
        (root / source).unlink()
    after = sum(p.stat().st_size for p in media.rglob('*') if p.is_file())
    print(f'PNG -> WebP: {len(mapping)}; CMS files updated: {sum(updated[p] != documents[p] for p in documents)}')
    print(f'Current media files: {before:,} -> {after:,} bytes')
    print('Past Git history is unchanged.')


if __name__ == '__main__':
    main()
