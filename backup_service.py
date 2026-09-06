"""Consistent database snapshots and complete, bounded controller file backups."""
import argparse
import ftplib
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


def controller_backup(config, device_id):
    if not config.get('host') or not config.get('user') or not config.get('password'):
        raise ValueError('控制器FTP地址和凭据必须显式配置')
    ftp=ftplib.FTP(timeout=10)
    files=[]
    total=0
    data=io.BytesIO()
    try:
        ftp.connect(config['host'],int(config.get('port',21)),timeout=10)
        ftp.login(config['user'],config['password'])
        with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:
            def walk(remote,depth=0):
                nonlocal total
                if depth>16:
                    raise ValueError('控制器目录层级超过备份限制')
                entries=list(ftp.mlsd(remote))
                for name,facts in entries:
                    if facts.get('type') in ('cdir','pdir') or name in ('.','..'):
                        continue
                    if any(x in name for x in ('/',chr(92),chr(13),chr(10))):
                        raise ValueError('非法控制器文件名')
                    path=(remote.rstrip('/')+'/'+name).lstrip('/')
                    if facts.get('type')=='dir':
                        walk(path,depth+1)
                    elif facts.get('type')=='file':
                        buf=io.BytesIO()
                        def collect(chunk):
                            nonlocal total
                            total+=len(chunk)
                            if total>256*1024*1024:
                                raise ValueError('控制器备份超过256MB限制')
                            buf.write(chunk)
                        ftp.retrbinary('RETR '+path,collect)
                        if len(files)>=2000:
                            raise ValueError('控制器备份文件数量超过限制')
                        payload=buf.getvalue()
                        if 'size' in facts and int(facts['size'])!=len(payload):
                            raise ValueError('控制器文件传输不完整')
                        archive.writestr(path,payload)
                        files.append({'path':path,'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()})
                    else:
                        raise ValueError('不支持的控制器文件类型，备份未标记成功')
            walk('/')
            if not files:
                raise ValueError('控制器未返回可备份文件，拒绝生成空备份')
            manifest={'device_id':device_id,'kind':'controller_files','complete':True,'files':files,
                      'created_at':datetime.now().astimezone().isoformat()}
            archive.writestr('backup_manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        return data.getvalue(),manifest
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


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
