"""Consistent database snapshots and complete, bounded controller file backups."""
import argparse
import hashlib
import io
import json
import os
import sqlite3
import uuid
import zipfile
from datetime import datetime
from pathlib import Path


def backup_directory():
    return Path(os.getenv('BACKUP_DIR',str(Path(__file__).parent/'backups'))).resolve()


def database_snapshot(source, destination):
    source=Path(source).resolve()
    destination=Path(destination).resolve()
    if source==destination or destination.exists():
        raise ValueError('Snapshot destination must be a new, distinct file')
    destination.parent.mkdir(parents=True,exist_ok=True)
    source_conn=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=10)
    target=sqlite3.connect(str(destination))
    try:
        source_conn.execute('BEGIN')
        source_conn.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()
        source_conn.backup(target,pages=256,sleep=0.01)
        if target.execute('PRAGMA quick_check').fetchone()[0]!='ok':
            raise RuntimeError('Backup verification failed')
    finally:
        target.close()
        source_conn.close()
    return destination


def platform_backup(source):
    """Create a verified platform archive without contacting the controller."""
    directory=backup_directory()
    directory.mkdir(parents=True,exist_ok=True)
    snapshot=directory/f'.snapshot_{uuid.uuid4().hex}.db'
    try:
        database_snapshot(source,snapshot)
        db_payload=snapshot.read_bytes()
        manifest={'kind':'platform_database','complete':True,
                  'created_at':datetime.now().astimezone().isoformat(),
                  'scope':'平台数据库一致性快照，不是控制器完整系统镜像'}
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('robot.db',db_payload)
            archive.writestr('backup_manifest.json',json.dumps(dict(manifest,
                database_bytes=len(db_payload),
                database_sha256=hashlib.sha256(db_payload).hexdigest()),
                ensure_ascii=False,indent=2))
        return data.getvalue(),manifest
    finally:
        try:
            snapshot.unlink()
        except FileNotFoundError:
            pass


def save_archive(payload, manifest, suffix):
    directory=backup_directory()
    directory.mkdir(parents=True,exist_ok=True)
    name=f"{manifest['kind']}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}{suffix}"
    path=directory/name
    path.write_bytes(payload)
    manifest=dict(manifest,filename=name,filesize=len(payload),sha256=hashlib.sha256(payload).hexdigest())
    (directory/(name+'.manifest.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return name


def list_backups(device_id=None):
    result=[]
    for path in backup_directory().glob('*.manifest.json'):
        try:
            m=json.loads(path.read_text(encoding='utf-8'))
            archive=backup_directory()/m['filename']
            if archive.parent.resolve()!=backup_directory() or not archive.is_file() or not m.get('complete'):
                continue
            if m.get('kind')=='controller_files' and m.get('device_id')!=device_id:
                continue
            if archive.stat().st_size!=m['filesize']:
                continue
            result.append(m)
        except (OSError,ValueError,KeyError):
            continue
    return sorted(result,key=lambda m:m['created_at'],reverse=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',default=os.getenv('DB_PATH','robot.db'))
    args=parser.parse_args()
    directory=backup_directory()
    directory.mkdir(parents=True,exist_ok=True)
    name=f'platform_database_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.db'
    path=database_snapshot(args.database,directory/name)
    digest=None
    if digest is None:
        hasher=hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda:source.read(1024*1024),b''):
                hasher.update(chunk)
        digest=hasher.hexdigest()
    manifest={'kind':'platform_database','complete':True,'filename':name,'filesize':path.stat().st_size,
              'sha256':digest,'created_at':datetime.now().astimezone().isoformat(),'scope':'平台数据库一致性快照，不是控制器完整系统镜像'}
    (directory/(name+'.manifest.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False))


if __name__=='__main__':
    main()
