"""Official SDK return-code reference, not a guessed hardware repair manual."""
import json
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent/'resources/huashu_sdk_errors.json').read_text(encoding='utf-8'))


def install_catalog(conn):
    data=catalog()
    for entry in data['entries']:
        description='; '.join(name+': '+text for name,text in zip(entry['symbols'],entry['definitions']))
        if len(entry['symbols'])>1:
            description+='。官方文件给同一数值定义了多个名称，不能据此唯一判定原因。'
        reference='official-sdk:'+data['source_file']+':'+','.join(str(n) for n in entry['source_lines'])
        conn.execute("""INSERT INTO alarm_knowledge_base(code,title,category,description,cause,solution,verified,reference)
            VALUES(?,?,?,?,?,?,1,?) ON CONFLICT(code) DO UPDATE SET
            title=excluded.title,category=excluded.category,description=excluded.description,cause=excluded.cause,
            solution=excluded.solution,verified=1,reference=excluded.reference
            WHERE alarm_knowledge_base.verified=0 OR alarm_knowledge_base.reference LIKE 'official-sdk:%'""",
            (entry['code'],' / '.join(entry['definitions']),entry['category'],description,
             '该官方定义文件未提供进一步原因',
             '该官方定义文件未提供维修步骤；请结合接口调用结果和对应控制器运维手册排查',reference))


def enrich(rows):
    data=catalog();lookup={r['code']:r for r in data['entries']}
    result=[]
    for row in rows:
        item=dict(row);entry=lookup.get(item['code'])
        if entry and item['reference'].startswith('official-sdk:'):
            item.update(decimal=entry['decimal'],symbols=entry['symbols'],scope=data['scope'],
                reference_display='ErrDef.h 第'+','.join(map(str,entry['source_lines']))+'行',
                duplicate_definition=len(entry['symbols'])>1,source_sha256=data['source_sha256'])
        result.append(item)
    return result

