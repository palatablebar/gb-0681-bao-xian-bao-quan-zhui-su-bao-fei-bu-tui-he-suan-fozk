import csv,io
from app.workflow import run,load
from app import store
from app.modules.m7_archive.export_out import bundle

def state():return run(load('merger.csv'),{})

def test_collision_split_keeps_new_system_number():
    # TRAP-27 同号不同人拆分，新系统登记保持原号
    ids={c['contract'] for c in state()['identities']}
    assert 'P100' in ids and 'P100@old' in ids
    keeper=next(c for c in state()['identities'] if c['contract']=='P100')
    assert keeper['insured']=='乙' and keeper['sources']==['new']

def test_collision_not_spliced():
    calc={c['id']:c for c in state()['calculations']}
    assert calc['P100@old']['expected']=='3650.00' and calc['P100@old']['paid']=='3650'
    assert calc['P100']['expected']=='1200.00' and calc['P100']['paid']=='1200'

def test_renewal_chain_attributes_to_root():
    # TRAP-28 续接换号归属原保单，已交保费按链汇总
    calc={c['id']:c for c in state()['calculations']}
    chain=calc['P200']
    assert chain['members']==['P200','P900'] and chain['expected']=='7650.00'
    assert chain['paid']=='4150' and chain['difference']=='3500.00'
    assert 'P900' not in calc

def test_cross_system_same_policy_merged():
    s=state();calc={c['id']:c for c in s['calculations']}
    assert calc['P300']['expected']=='5490.00' and calc['P300']['paid']=='3650'
    assert s['duplicate_count']==1
    ident=next(c for c in s['identities'] if c['contract']=='P300')
    assert ident['sources']==['new','old']

def test_dangling_renewal_quarantined_not_dropped():
    # TRAP-29 归并失败隔离留痕，对账仍平
    s=state()
    assert any(q['id']=='40001' and q['code']=='IDENTITY' for q in s['quarantine'])
    assert s['reconcile']['balanced'] is True
    assert all(c['id']!='P400' for c in s['calculations'])

def test_missing_insured_in_collision_quarantined():
    assert any(q['id']=='10003' and q['code']=='IDENTITY' for q in state()['quarantine'])

def test_cycle_renewal_quarantined():
    text='id,policy_id,version,kind,effective,start,end,annual_premium,paid,ref,cover,note,source,insured,renewal_of\n'\
        '1,A,1,issue,2026-01-01,2026-01-01,2027-01-01,100,0,,基础险,环甲,new,甲,B\n'\
        '2,B,1,issue,2026-01-01,2026-01-01,2027-01-01,100,0,,基础险,环乙,new,乙,A\n'
    s=run(text.encode(),{})
    assert s['calculations']==[] and sum(1 for q in s['quarantine'] if q['code']=='IDENTITY')==2
    assert s['reconcile']['balanced'] is True

def test_old_system_self_collision_quarantined():
    text='id,policy_id,version,kind,effective,start,end,annual_premium,paid,ref,cover,note,source,insured,renewal_of\n'\
        '1,P500,1,issue,2026-01-01,2026-01-01,2027-01-01,100,0,,基础险,旧甲,old,甲,\n'\
        '2,P500,1,issue,2026-01-01,2026-01-01,2027-01-01,100,0,,基础险,旧乙,old,乙,\n'
    s=run(text.encode(),{})
    assert s['calculations']==[] and sum(1 for q in s['quarantine'] if q['code']=='IDENTITY')==2

HEADER='id,policy_id,version,kind,effective,start,end,annual_premium,paid,ref,cover,note,source,insured,renewal_of\n'
def test_chain_of_three_attributes_to_root():
    s=run((HEADER+'1,A,1,issue,2024-01-01,2024-01-01,2025-01-01,100,100,,基础险,原,old,甲,\n'
        '2,B,1,issue,2025-01-01,2025-01-01,2026-01-01,100,50,,基础险,续一,new,甲,A\n'
        '3,C,1,issue,2026-01-01,2026-01-01,2027-01-01,100,25,,基础险,续二,new,甲,B\n').encode(),{})
    calc={c['id']:c for c in s['calculations']}
    assert list(calc)==['A'] and calc['A']['members']==['A','B','C'] and calc['A']['paid']=='175'

def test_ambiguous_bare_number_renewal_quarantined():
    s=run((HEADER+'1,P100,1,issue,2026-01-01,2026-01-01,2027-01-01,100,10,,基础险,旧甲,old,甲,\n'
        '2,P100,1,issue,2026-01-01,2026-01-01,2027-01-01,200,20,,基础险,新乙,new,乙,\n'
        '3,P888,1,issue,2026-01-01,2026-01-01,2027-01-01,300,30,,基础险,多义续接,new,丙,P100\n').encode(),{})
    assert any(q['id']=='3' and q['code']=='IDENTITY' for q in s['quarantine'])
    assert {c['contract'] for c in s['identities']}=={'P100','P100@old'} and s['reconcile']['balanced']

def test_renewal_exact_suffixed_id_resolves():
    s=run((HEADER+'1,P100,1,issue,2026-01-01,2026-01-01,2027-01-01,100,10,,基础险,旧甲,old,甲,\n'
        '2,P100,1,issue,2026-01-01,2026-01-01,2027-01-01,200,20,,基础险,新乙,new,乙,\n'
        '3,P777,1,issue,2026-01-01,2026-01-01,2027-01-01,300,30,,基础险,续旧甲,new,甲,P100@old\n').encode(),{})
    calc={c['id']:c for c in s['calculations']}
    assert calc['P100@old']['members']==['P100@old','P777'] and calc['P100@old']['paid']=='40'

def test_invalid_source_quarantined():
    s=run((HEADER+'1,A,1,issue,2026-01-01,2026-01-01,2027-01-01,100,0,,基础险,坏来源,middle,甲,\n').encode(),{})
    assert s['quarantine'][0]['code']=='IDENTITY' and s['reconcile']['balanced']

def test_rerun_adds_no_policy_or_supplement(tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'r.db'))
    raw=load('merger.csv');a=run(raw,{});b=run(raw,{})
    assert a['run_id']==b['run_id']
    assert [c['id'] for c in a['calculations']]==[c['id'] for c in b['calculations']]
    store.save(a['run_id'],a);store.save(b['run_id'],b)
    assert len(store.history())==1
    assert len(store.get(a['run_id'])['calculations'])==4

def test_archive_export_uses_same_attribution():
    s=state();text=bundle(s)
    assert '归并' in text and 'P100@old' in text
    rows=list(csv.reader(io.StringIO(text.lstrip('﻿'))))
    calc_ids={r[3] for r in rows if r[0]=='计算'}
    assert calc_ids=={c['owner'] for c in s['identities']}

def test_legacy_samples_unaffected():
    s=run(load('dirty.csv'),{})
    assert s['identities']==[]
    assert all(c['members']==[c['id']] for c in s['calculations'])
