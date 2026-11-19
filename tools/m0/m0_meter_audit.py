#!/usr/bin/env python3
"""Reproducible LADOT M0 inventory/occupancy audit; standard library only.

Run with public network connectivity. This is a research utility, not production ETL.
No real data is bundled in this project.
"""
import argparse, collections, csv, datetime as dt, json, math, pathlib, re, urllib.parse, urllib.request

UTC = dt.timezone.utc
BASE = 'https://data.lacity.org/resource/'
FIELDS = {'inventory': ['spaceid','blockface','metertype','ratetype','raterange','timelimit','latlng'],
          'occupancy': ['spaceid','eventtime','occupancystate']}
DATASETS = {'inventory':'s49e-q6j2', 'occupancy':'e7h6-4a3e'}

def fetch_data(kind, limit):
    params = urllib.parse.urlencode({'$limit':limit, '$order':'spaceid'})
    url = f'{BASE}{DATASETS[kind]}.csv?{params}'
    request = urllib.request.Request(url, headers={'User-Agent':'CurbOS-M0-data-audit/0.1 (research)'})
    with urllib.request.urlopen(request, timeout=60) as res:
        data = res.read(25_000_001)
        if len(data)>25_000_000: raise ValueError('Data exceeds 25MB audit cap')
    return data.decode('utf-8-sig'),url

def load_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as fh:
        rdr = csv.DictReader(fh)
        rows = list(rdr)
        fields = list(rdr.fieldnames or [])
    return rows,fields

def parse_time(value):
    if not value or not value.strip(): return None
    s=value.strip().replace('Z','+00:00')
    try:
        d=dt.datetime.fromisoformat(s)
        # The LADOT field is explicitly named EventTime_UTC; naive timestamps assumed UTC.
        return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)
    except ValueError: return None

def percent(a,b): return round(100*a/b,2) if b else None

def quantile(xs,q):
    if not xs:return None
    vals=sorted(xs)
    pos=(len(vals)-1)*q
    lo=math.floor(pos);hi=math.ceil(pos)
    return round(vals[lo]+(vals[hi]-vals[lo])*(pos-lo),2)

def parse_coords(raw):
    """Recognize a few common Socrata CSV location encodings; unknown returns None."""
    s=(raw or '').strip()
    if not s:return None
    if s.upper().startswith('POINT'):
        nums=re.findall(r'-?\d+(?:\.\d+)?',s)
        if len(nums)==2:
            lon,lat=map(float,nums)
            return (lat,lon)
    nums=re.findall(r'-?\d+(?:\.\d+)?',s)
    if len(nums)!=2:return None
    a,b=map(float,nums)
    if -90<=a<=90 and -180<=b<=180:return (a,b)
    if -180<=a<=180 and -90<=b<=90:return (b,a)
    return None

def summary(inventory, occupancy, anchor):
    inv_ids=[r.get('spaceid','').strip() for r in inventory]
    occ_ids=[r.get('spaceid','').strip() for r in occupancy]
    inv_set=set(x for x in inv_ids if x)
    occ_set=set(x for x in occ_ids if x)
    shared=inv_set & occ_set
    missing_inventory=[x for x in occ_set if x not in inv_set]
    ages=[];invalid_ts=0;future_ts=0;timestamp_missing=0
    current_states=collections.Counter()
    age_under={str(t):0 for t in (5,15,60)}
    for r in occupancy:
        current_states[r.get('occupancystate','').strip() or '<EMPTY>']+=1
        raw=r.get('eventtime','')
        if not raw or not raw.strip():timestamp_missing+=1;continue
        d=parse_time(raw)
        if d is None: invalid_ts+=1;continue
        age=(anchor-d).total_seconds()/60
        if age < 0:future_ts+=1;continue
        ages.append(age)
        for t in (5,15,60):
            if age<=t:age_under[str(t)]+=1
    coord_rows=[parse_coords(r.get('latlng','')) for r in inventory]
    bad_coords=sum(bool(r.get('latlng','').strip()) and coord_rows[i] is None for i,r in enumerate(inventory))
    # Broad regional sanity bounds only, NOT an official City of LA jurisdiction boundary.
    outside_region=sum(c is not None and not (33.6<=c[0]<=34.5 and -119.0<=c[1]<=-117.5) for c in coord_rows)
    inv_dupes=sum(n-1 for n in collections.Counter(inv_ids).values() if n>1)
    occ_dupes=sum(n-1 for n in collections.Counter(occ_ids).values() if n>1)
    return {
      'reference_time_utc': anchor.isoformat(),
      'inventory':{'rows':len(inventory),'unique_nonempty_spaceids':len(inv_set),'empty_spaceids':inv_ids.count(''),'duplicate_id_extra_rows':inv_dupes,'blank_latlng_rows':sum(not r.get('latlng','').strip() for r in inventory),'unparseable_nonblank_latlng_rows':bad_coords,'outside_broad_regional_bbox_rows':outside_region,'blank_blockface_rows':sum(not r.get('blockface','').strip() for r in inventory),'rate_types':dict(collections.Counter(r.get('ratetype','').strip() or '<EMPTY>' for r in inventory))},
      'occupancy':{'rows':len(occupancy),'unique_nonempty_spaceids':len(occ_set),'empty_spaceids':occ_ids.count(''),'duplicate_id_extra_rows':occ_dupes,'occupancy_states':dict(current_states),'missing_timestamps':timestamp_missing,'invalid_timestamps':invalid_ts,'future_timestamps':future_ts},
      'join':{'matched_unique_spaceids':len(shared),'unmatched_occupancy_unique_spaceids':len(missing_inventory),'occupancy_to_inventory_match_pct':percent(len(shared),len(occ_set)),'inventory_sensor_coverage_pct':percent(len(shared),len(inv_set))},
      'freshness_all_occupancy_rows':{'valid_nonfuture_timestamp_rows':len(ages),'p50_age_min':quantile(ages,.5),'p90_age_min':quantile(ages,.9),'p95_age_min':quantile(ages,.95),'max_age_min':round(max(ages),2) if ages else None,'share_of_all_occupancy_rows_at_most_min_pct':{k:percent(v,len(occupancy)) for k,v in age_under.items()}},
      'caveats':['Snapshot ages are relative to reference time and depend on provider timestamp semantics.', 'Missing or invalid timestamps are excluded from age percentiles, but counted against shares of all occupancy rows.', 'Coverage rates are not citywide if files are partial.','SpaceID equality is exact after trimming whitespace; additional mapping checks may be needed.','The regional coordinate sanity bounding box is not a City of LA polygon and cannot validate jurisdiction.','No legal parking eligibility or price accuracy can be concluded from this audit.']
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fetch',action='store_true', help='Download bounded public Socrata CSV; requires internet')
    ap.add_argument('--inventory',type=pathlib.Path,default=pathlib.Path('inventory.csv'))
    ap.add_argument('--occupancy',type=pathlib.Path,default=pathlib.Path('occupancy.csv'))
    ap.add_argument('--inventory-limit',type=int,default=40000)
    ap.add_argument('--occupancy-limit',type=int,default=10000)
    ap.add_argument('--reference-time',help='ISO-8601 offset-aware snapshot reference UTC time; default current UTC')
    ap.add_argument('--output',type=pathlib.Path,default=pathlib.Path('m0_audit_results.json'))
    args=ap.parse_args()
    if args.fetch:
        for kind,path,limit in [('inventory',args.inventory,args.inventory_limit),('occupancy',args.occupancy,args.occupancy_limit)]:
            if limit<1 or limit>50000:ap.error('limits must be 1..50000')
            data,url=fetch_data(kind,limit)
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(data,encoding='utf-8')
            print('Downloaded',kind,'from',url,'to',path)
    rows={}
    for kind,path in [('inventory',args.inventory),('occupancy',args.occupancy)]:
        values,cols=load_csv(path)
        missing=set(FIELDS[kind])-set(cols)
        if missing:ap.error(f'{kind}: missing required columns {sorted(missing)}; available {cols}')
        rows[kind]=values
    anchor=parse_time(args.reference_time) if args.reference_time else dt.datetime.now(UTC)
    if anchor is None:ap.error('reference time must be valid ISO-8601')
    result=summary(rows['inventory'],rows['occupancy'],anchor)
    result['audit_mode']='full_candidate' if len(rows['inventory'])<args.inventory_limit and len(rows['occupancy'])<args.occupancy_limit and args.fetch else 'sample_or_unverified_scope'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False))
    print('Saved report:',args.output)

if __name__=='__main__':main()
