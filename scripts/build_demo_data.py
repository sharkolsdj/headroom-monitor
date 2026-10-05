"""Build compact per-scenario JSON files for the static demo (frontend/demo) from data/demo outputs."""
import json, csv, os, statistics as st
R=os.path.join(os.path.dirname(__file__),'..','data','demo')
OUT=os.path.join(os.path.dirname(__file__),'..','frontend','demo','data')
IDS=['S1_normal','S2_big_customer','S3_sector_crisis','S4_outflow_spike','S5_seasonality','S6_new_customer','S7_partial_payments','S8_month_end_close','H1_drift','H2_sector']
acc={}
for f in ['accuracy_summary.csv','holdout_accuracy.csv']:
    for r in csv.DictReader(open(f'{R}/{f}')): acc[r['dataset_id']]=r
r2=lambda x: None if x is None else round(x,2)
summary=[]
for ds in IDS:
    F=json.load(open(f'{R}/{ds}/forecast.json'))
    sc=F['scenarios']; band=F['mc_band']
    weeks=[]
    for i,w in enumerate(sc['expected']['weeks']):
        b=band[str(w['week'])]
        weeks.append({'w':w['week'],'s':w['week_start'],'e':w['week_end'],'open':r2(w['opening']),'rec':r2(w['receipts']),'pay':r2(w['payments']),
          'close':r2(w['closing']),'pbs':{k:r2(v) for k,v in w['payments_by_source'].items()},
          'ontime':r2(sc['on_time']['weeks'][i]['closing']),'stress':r2(sc['stress']['weeks'][i]['closing']),
          'p10':r2(b['p10']),'p50':r2(b['p50']),'p90':r2(b['p90']),'pb':b['p_below_threshold']})
    C=json.load(open(f'{R}/{ds}/customers.json'))
    cust=[]
    for c in C:
        cust.append({'c':c['cust_code'],'seg':c['segment'],'rank':c['priority_rank'],'owed':r2(c['total_owed']),'od':r2(c['overdue_amount']),
          'typ':c['typical_delay_days'],'rec':c['recent_delay_days'],'trend':c['trend'],'src':c['source'],'txt':c['sentence'],
          'inv':[{'id':i['invoice_id'],'due':i['due_date'],'amt':r2(i['outstanding']),'dod':i['days_overdue'],'dtd':i['days_to_due'],
                  'p10':i['p10_date'],'p50':i['p50_date'],'p90':i['p90_date'],'rb':i['remind_by'],'why':i['reason_code']} for i in c['open_invoices']]})
    coll=json.load(open(f'{R}/{ds}/collections.json'))[:25]
    a=acc.get(ds,{})
    out={'id':ds,'as_of':F['as_of'],'threshold':F['threshold'],'opening':F['opening_balance'],'weeks':weeks,
         'alerts':F['sector_alerts'] or [],'bridge':F['bridge'] or [],'assumptions':F['assumptions'] or [],
         'collections':coll,'customers':cust,'accuracy':a}
    if os.path.exists(f'{R}/{ds}/actual.json'): out['actual']=json.load(open(f'{R}/{ds}/actual.json'))
    json.dump(out,open(f'{OUT}/{ds}.json','w'),separators=(',',':'))
    first=next((w['w'] for w in weeks if w['close']<F['threshold']),None)
    mn=min(weeks,key=lambda w:w['close'])
    summary.append((ds,first,mn['w'],round(mn['close']),max(w['pb'] for w in weeks),[ (w['w'],round(w['close']/1e3),round(w['pb'],2)) for w in weeks]))


