from app.errors import DomainError
from app.modules.m2_mapping.coerce import SENTINELS

SOURCES={'OLD':'old','LEGACY':'old','NEW':'new'}
COLUMNS=('source','insured','renewal_of')

def _optional(value):
    text=str(value if value is not None else '').strip()
    return None if text.upper() in SENTINELS else text

def _source(value):
    text=_optional(value)
    if text is None:return None
    tag=SOURCES.get(text.upper())
    if tag is None:raise DomainError('IDENTITY','来源系统无法识别')
    return tag

def resolve(state):
    rows=state.get('rows',[])
    if not rows or not any(column in rows[0] for column in COLUMNS):
        for row in rows:row['contract_id']=row['owner_id']=row['policy_id']
        state['identities']=[]
        return state
    failed={};by_line={}
    for row in rows:
        by_line[row['_line']]=row
        try:row['_source']=_source(row.get('source'))
        except DomainError:failed[row['_line']]='IDENTITY'
        row['_insured']=_optional(row.get('insured'))
        row['_renewal']=_optional(row.get('renewal_of'))
    numbers={}
    for row in rows:
        if row['_line'] not in failed:numbers.setdefault(row['policy_id'],[]).append(row)
    contracts={}
    for number,members in numbers.items():
        insureds=sorted({m['_insured'] for m in members if m['_insured'] is not None})
        if len(insureds)<=1:
            contracts[number]={'number':number,'insured':insureds[0] if insureds else None,'rows':members,'basis':None}
            continue
        # 同号碰撞：按被保人拆分，以新系统登记为准
        for m in members:
            if m['_insured'] is None:failed[m['_line']]='IDENTITY'
        groups={i:[m for m in members if m['_insured']==i] for i in insureds}
        keeper=[i for i in insureds if any(m['_source']=='new' for m in groups[i])]
        if len(keeper)>1:
            for m in members:failed[m['_line']]='IDENTITY'
            continue
        if keeper:
            contracts[number]={'number':number,'insured':keeper[0],'rows':groups[keeper[0]],'basis':'同号拆分·新系统为准'}
        old_only=[i for i in insureds if not keeper or i!=keeper[0]]
        for i in old_only:
            group=groups[i]
            if len(old_only)>1 or any(m['_source']!='old' for m in group):
                for m in group:failed[m['_line']]='IDENTITY'
            else:
                contracts[number+'@old']={'number':number,'insured':i,'rows':group,'basis':'同号拆分·旧系统侧'}
    # 续接链：归属链根（原保单），环与悬空引用隔离不丢弃
    for cid in list(contracts):
        renewals={m['_renewal'] for m in contracts[cid]['rows'] if m['_renewal'] is not None}
        if len(renewals)>1:
            for m in contracts[cid]['rows']:failed[m['_line']]='IDENTITY'
            del contracts[cid]
        else:contracts[cid]['renewal_of']=renewals.pop() if renewals else None
    def find(target):
        if target in contracts and contracts[target]['number']!=target:return target
        matches=[cid for cid,info in contracts.items() if info['number']==target]
        return matches[0] if len(matches)==1 else None
    owners={}
    for cid in contracts:
        seen={cid};cursor=cid
        while contracts[cursor]['renewal_of'] is not None:
            parent=find(contracts[cursor]['renewal_of'])
            if parent is None or parent in seen:break
            seen.add(parent);cursor=parent
        else:owners[cid]=cursor;continue
        owners[cid]=None
    for cid,owner in owners.items():
        if owner is None:
            for m in contracts[cid]['rows']:failed[m['_line']]='IDENTITY'
    contracts={cid:info for cid,info in contracts.items() if owners[cid] is not None}
    for cid,info in contracts.items():
        sources=set()
        for m in info['rows']:
            sources.update(m.get('_sources') or [])
            if m['_source']:sources.add(m['_source'])
        info['sources']=sorted(sources)
        for m in info['rows']:
            m['contract_id']=cid;m['owner_id']=owners[cid]
        if info['basis'] is None:
            if info['renewal_of']:info['basis']='续接归并·归属原保单'
            elif any(owners[other]==cid and other!=cid for other in contracts):info['basis']='续接链根·原保单'
            elif len(info['sources'])>1:info['basis']='跨系合并·同人同号'
            else:info['basis']='单源直挂'
    state['identities']=[{'contract':cid,'owner':owners[cid],'number':info['number'],
        'insured':info['insured'] or '','sources':info['sources'],
        'renewal_of':info['renewal_of'] or '','basis':info['basis']} for cid,info in sorted(contracts.items())]
    for row in rows:
        for key in ('_source','_insured','_renewal','_sources'):row.pop(key,None)
    for line in sorted(failed):
        row=by_line[line]
        state['quarantine'].append({'line':line,'id':row['id'],'code':failed[line],'raw':row['_raw']})
    state['rows']=[row for row in rows if row['_line'] not in failed]
    return state
