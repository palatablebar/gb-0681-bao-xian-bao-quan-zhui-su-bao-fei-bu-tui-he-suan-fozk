from copy import deepcopy
from app.config import REQUIRED,NUMERIC,DATES,TIMES
from app.errors import DomainError
from app.modules.m2_mapping.coerce import number,day,instant,SENTINELS
from app.modules.m2_mapping.identity import SOURCES

def _source_tag(row):
    return SOURCES.get(str(row.get('source','') or '').strip().upper())

def normalize(state):
    state=deepcopy(state);good=[];groups={}
    for row in state['rows']:
        try:
            for field in REQUIRED:
                if str(row.get(field,'')).strip().upper() in SENTINELS:raise DomainError('MISSING','必填值缺失')
            item=dict(row)
            for field in NUMERIC:
                if field in item and item[field] != '':item[field]=number(item[field])
            for field in DATES:
                if field in item and item[field] != '':item[field]=day(item[field])
            for field in TIMES:
                if field in item and item[field] != '':item[field]=instant(item[field])
            key=(item['id'],str(item.get('version','1')))
            groups.setdefault(key,[]).append(item)
        except DomainError as error:state['quarantine'].append({'line':row['_line'],'id':row.get('id',''),'code':error.code,'raw':row['_raw']})
    for key,rows in groups.items():
        # 迁移副本仅来源列不同视为重复，保留新系统侧；其余内容冲突整组隔离
        unique={str(sorted((k,str(v)) for k,v in r.items() if not k.startswith('_') and k!='source')) for r in rows}
        if len(unique)>1:
            for r in rows:state['quarantine'].append({'line':r['_line'],'id':r['id'],'code':'CONFLICT','raw':r['_raw']})
        else:
            keeper=next((r for r in rows if _source_tag(r)=='new'),rows[0])
            sources=sorted({tag for tag in (_source_tag(r) for r in rows) if tag})
            if len(sources)>1:keeper['_sources']=sources
            good.append(keeper);state['duplicate_count']+=len(rows)-1
    state['rows']=good
    return state
