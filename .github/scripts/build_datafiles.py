#!/usr/bin/env python3
"""Check the BattleScribe datafiles and build the release assets.

This replaces BSData/check-datafiles and BSData/publish-catpkg, which can no
longer be resolved on GitHub. It produces the same set of assets the
2024.06.06 release of LeonisAstra/30K-4-All carried:

  <name>.latest.bsi        zip holding <name>.latest.xml (a dataIndex) - the
                           install link for New Recruit / BattleScribe
  <name>.catpkg.json(.gz)  repository description in the BSData catpkg format
  <name>.<tag>.bsr         zip of index.xml plus every raw datafile
  <file>.catz / <file>.gstz  each datafile zipped on its own

Usage:
  build_datafiles.py check
  build_datafiles.py build --out DIR --repo OWNER/NAME --tag TAG
                           [--description TEXT] [--notes TEXT]
"""
import argparse
import datetime
import gzip
import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from xml.sax.saxutils import quoteattr

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
NS = {'cat': 'http://www.battlescribe.net/schema/catalogueSchema',
      'gst': 'http://www.battlescribe.net/schema/gameSystemSchema'}


def datafiles():
    return sorted(f for f in os.listdir(ROOT) if f.endswith(('.cat', '.gst')))


def asset_name(filename):
    # GitHub renames uploaded assets the same way: anything outside
    # [A-Za-z0-9._-] becomes '.', e.g. "2022 - LA - Emperor's Children.cat"
    # -> "2022.-.LA.-.Emperor.s.Children.cat".
    return re.sub(r'[^A-Za-z0-9._-]', '.', filename)


def read_info(filename):
    root = ET.parse(os.path.join(ROOT, filename)).getroot()
    tag = root.tag.split('}')[-1]
    return {
        'file': filename,
        'type': 'gamesystem' if tag == 'gameSystem' else 'catalogue',
        'id': root.get('id'),
        'name': root.get('name'),
        'revision': int(root.get('revision') or 0),
        'battleScribeVersion': root.get('battleScribeVersion'),
        'gameSystemId': root.get('gameSystemId'),
        'authorName': root.get('authorName'),
        'authorContact': root.get('authorContact'),
        'authorUrl': root.get('authorUrl'),
        'root': root,
    }


def check():
    errors = []
    infos = []
    for f in datafiles():
        try:
            infos.append(read_info(f))
        except ET.ParseError as e:
            errors.append(f'{f}: XML parse error: {e}')
    systems = [i for i in infos if i['type'] == 'gamesystem']
    if len(systems) != 1:
        errors.append(f'expected exactly one .gst, found {len(systems)}')
    ids = {}
    for i in infos:
        if not i['id']:
            errors.append(f"{i['file']}: missing id")
        elif i['id'] in ids:
            errors.append(f"{i['file']}: id {i['id']} also used by {ids[i['id']]}")
        else:
            ids[i['id']] = i['file']
        if i['type'] == 'catalogue' and systems and i['gameSystemId'] != systems[0]['id']:
            errors.append(f"{i['file']}: gameSystemId {i['gameSystemId']} does not match {systems[0]['id']}")
    # Every catalogueLink must point at a catalogue in this repo.
    for i in infos:
        for link in i['root'].iter():
            if link.tag.endswith('catalogueLink') and link.get('targetId') not in ids:
                errors.append(f"{i['file']}: catalogueLink {link.get('name')!r} targets missing id {link.get('targetId')}")
    for i in infos:
        print(f"ok  {i['type']:10} r{i['revision']:<5} {i['file']}")
    for e in errors:
        print(f'ERROR {e}')
    print(f'{len(infos)} datafiles, {len(errors)} errors')
    return infos, errors


def zip_one(path, arcname, data):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(arcname, data)


def index_xml(name, entries, index_url=None):
    head = f'<dataIndex battleScribeVersion="2.03" name={quoteattr(name)}'
    if index_url:
        head += f' indexUrl={quoteattr(index_url)}'
    head += ' xmlns="http://www.battlescribe.net/schema/dataIndexSchema">'
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', head, '  <dataIndexEntries>']
    for path, i in entries:
        lines.append('    <dataIndexEntry filePath=%s dataType="%s" dataId=%s dataName=%s '
                     'dataBattleScribeVersion=%s dataRevision="%d"/>' % (
                         quoteattr(path), i['type'], quoteattr(i['id']), quoteattr(i['name']),
                         quoteattr(i['battleScribeVersion'] or '2.03'), i['revision']))
    lines += ['  </dataIndexEntries>', '</dataIndex>', '']
    return '\n'.join(lines).encode('utf-8')


def build(out, repo, tag, description, notes):
    infos, errors = check()
    if errors:
        sys.exit('datafile check failed, not building')
    os.makedirs(out, exist_ok=True)
    name = repo.split('/')[-1]
    base = f'https://github.com/{repo}'
    latest = f'{base}/releases/latest/download'
    tagged = f'{base}/releases/download/{tag}'
    index_url = f'{latest}/{name}.latest.bsi'

    zipped, raw, files = [], [], []
    for i in infos:
        data = open(os.path.join(ROOT, i['file']), 'rb').read()
        ext = 'gstz' if i['type'] == 'gamesystem' else 'catz'
        stem = asset_name(os.path.splitext(i['file'])[0])
        zname = f'{stem}.{ext}'
        zip_one(os.path.join(out, zname), i['file'], data)
        zipped.append((zname, i))
        raw.append((asset_name(i['file']), i, data))
        files.append({
            'id': i['id'], 'name': i['name'], 'type': i['type'], 'revision': i['revision'],
            'battleScribeVersion': i['battleScribeVersion'],
            'fileUrl': f'{tagged}/{zname}',
            'githubUrl': f"{base}/blob/{tag}/{i['file'].replace(' ', '%20')}",
            'bugTrackerUrl': f'{base}/issues',
            'authorName': i['authorName'], 'authorContact': i['authorContact'], 'authorUrl': i['authorUrl'],
            'sourceSha256': hashlib.sha256(data).hexdigest().upper(),
        })

    zip_one(os.path.join(out, f'{name}.latest.bsi'), f'{name}.latest.xml',
            index_xml(description, zipped, index_url))

    with zipfile.ZipFile(os.path.join(out, f'{name}.{tag}.bsr'), 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('index.xml', index_xml(description, [(a, i) for a, i, _ in raw]))
        for a, _, data in raw:
            z.writestr(a, data)

    pkg = {
        '$schema': 'https://raw.githubusercontent.com/BSData/schemas/master/src/catpkg.schema.json',
        'name': name,
        'description': description,
        'battleScribeVersion': '2.03',
        'version': tag,
        'lastUpdated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'lastUpdateDescription': notes or tag,
        'indexUrl': index_url,
        'repositoryUrl': f'{latest}/{name}.catpkg.json',
        'repositoryGzipUrl': f'{latest}/{name}.catpkg.json.gz',
        'repositoryBsrUrl': f'{tagged}/{name}.{tag}.bsr',
        'githubUrl': base,
        'feedUrl': f'{base}/releases.atom',
        'bugTrackerUrl': f'{base}/issues',
        'repositoryFiles': files,
    }
    js = json.dumps(pkg, indent=2).encode('utf-8')
    open(os.path.join(out, f'{name}.catpkg.json'), 'wb').write(js)
    with gzip.open(os.path.join(out, f'{name}.catpkg.json.gz'), 'wb') as g:
        g.write(js)
    print(f'built {len(os.listdir(out))} assets in {out}; install link: {index_url}')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('check')
    b = sub.add_parser('build')
    b.add_argument('--out', required=True)
    b.add_argument('--repo', required=True)
    b.add_argument('--tag', required=True)
    b.add_argument('--description', default='BSData Repository for 30K Fan Content')
    b.add_argument('--notes', default='')
    a = p.parse_args()
    if a.cmd == 'check':
        sys.exit(1 if check()[1] else 0)
    build(a.out, a.repo, a.tag, a.description, a.notes)
