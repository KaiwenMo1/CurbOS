#!/usr/bin/env python3
"""CurbOS M0-08: offline-first LADOT Code the Curb CDS snapshot audit.

Research tool, NOT production ETL and NOT a parking-legality engine.

Requires Python 3.10+; no external packages.
Usage:
    python m0_08_cds_audit.py --download
    python m0_08_cds_audit.py --zones LADOT_Zones.json --policies LADOT_Policies.json
    python m0_08_cds_audit.py --zones LADOT_Zones.json --policies LADOT_Policies.json --out audit.json

--download needs internet access and stores untouched source files locally. Inputs are
never modified. Results include source checksums, schema-discovery evidence, link
coverage, and limitations. Neither `rate=0` nor `undesignated` implies legal parking.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

BASE = 'https://rosap.ntl.bts.gov/view/dot/94217/'
URLS = {'zones': BASE + 'dot_94217_DS13.json',
        'policies': BASE + 'dot_94217_DS11.json'}


def download(url: str, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.partial')
    request = Request(url, headers={'User-Agent': 'CurbOS-M0-Research/0.1'})
    try:
        with urlopen(request, timeout=75) as response, temporary.open('wb') as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def load(path: Path):
    raw = path.read_bytes()
    obj = json.loads(raw)
    return obj, {'filename': str(path), 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}


def find_records(obj, kind):
    """CDS often uses data:[{zones:[...] or policies:[...]}]; tolerate wrappers.

    Stop on unknown structure instead of inventing row counts.
    """
    if not isinstance(obj, dict):
        raise ValueError(f'{kind}: top-level JSON must be an object')
    data = obj.get('data')
    possible = []
    if isinstance(data, list):
        for i, group in enumerate(data):
            if isinstance(group, dict) and isinstance(group.get(kind), list):
                possible.append((f'data[{i}].{kind}', group[kind]))
    elif isinstance(data, dict) and isinstance(data.get(kind), list):
        possible.append((f'data.{kind}', data[kind]))
    if isinstance(obj.get(kind), list):
        possible.append((kind, obj[kind]))
    if not possible:
        raise ValueError(f'{kind}: cannot discover record array; top-level keys={list(obj)[:30]}')
    records = [r for _, part in possible for r in part]
    return records, [name for name, _ in possible]


def get_zone_policy_refs(zone):
    """Extract common CDS shapes; record all found IDs, but never infer legality."""
    refs = []
    containers = [zone]
    for key in ('properties', 'attributes'):
        if isinstance(zone.get(key), dict):
            containers.append(zone[key])
    for owner in containers:
        for key in ('curb_policy_ids', 'policy_ids', 'curb_policies'):
            value = owner.get(key)
            if value is None:
                continue
            if not isinstance(value, list):
                value = [value]
            for item in value:
                if isinstance(item, str):
                    refs.append(item)
                elif isinstance(item, dict):
                    x = item.get('curb_policy_id') or item.get('policy_id')
                    if x is not None:
                        refs.append(str(x))
    return refs


def get_zone_id(z):
    for owner in (z, z.get('properties', {})):
        if isinstance(owner, dict):
            for key in ('curb_zone_id', 'zone_id', 'id'):
                if owner.get(key) is not None:
                    return str(owner[key])
    return None


def zone_geometry(z):
    g = z.get('geometry')
    if not isinstance(g, dict) and isinstance(z.get('properties'), dict):
        g = z['properties'].get('geometry')
    return g if isinstance(g, dict) else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--download', action='store_true', help='download official snapshots before audit')
    ap.add_argument('--zones', type=Path, default=Path('LADOT_Zones.json'))
    ap.add_argument('--policies', type=Path, default=Path('LADOT_Policies.json'))
    ap.add_argument('--out', type=Path, default=Path('M0_08_audit_results.json'))
    a = ap.parse_args()
    if a.download:
        for kind, path in [('zones', a.zones), ('policies', a.policies)]:
            print(f'Downloading {kind} from {URLS[kind]} ...', file=sys.stderr)
            download(URLS[kind], path)
    for path in [a.zones, a.policies]:
        if not path.exists():
            ap.error(f'Missing {path}; use --download or supply --zones/--policies')

    zroot, zfile = load(a.zones)
    proot, pfile = load(a.policies)
    zones, zpaths = find_records(zroot, 'zones')
    policies, ppaths = find_records(proot, 'policies')
    if not all(isinstance(r, dict) for r in zones + policies):
        raise ValueError('Found non-object records in official dataset')

    ids = [get_zone_id(z) for z in zones]
    known = set()
    policy_ids = []
    for p in policies:
        pid = p.get('curb_policy_id')
        policy_ids.append(str(pid) if pid is not None else None)
        if pid is not None:
            known.add(str(pid))

    refs_by_zone = [get_zone_policy_refs(z) for z in zones]
    distinct_refs = set(ref for refs in refs_by_zone for ref in refs)
    missing_refs = sorted(distinct_refs - known)
    with_refs = sum(bool(r) for r in refs_by_zone)
    fully_resolved = sum(bool(refs) and all(ref in known for ref in refs) for refs in refs_by_zone)
    unknown_refs_zones = sum(any(r not in known for r in refs) for refs in refs_by_zone)
    geo = [zone_geometry(z) for z in zones]

    activities = Counter()
    user_class_forms = Counter()
    user_classes = Counter()
    rules_count = 0
    for policy in policies:
        for rule in policy.get('rules', []) if isinstance(policy.get('rules'), list) else []:
            if not isinstance(rule, dict):
                continue
            rules_count += 1
            activities[str(rule.get('activity'))] += 1
            uc = rule.get('user_classes')
            user_class_forms[type(uc).__name__] += 1
            values = uc if isinstance(uc, list) else [uc]
            for v in values:
                user_classes[str(v)] += 1

    zid_nonnull = [x for x in ids if x]
    pid_nonnull = [x for x in policy_ids if x]
    zone_types = Counter(g.get('type', '<missing>') if g else '<missing>' for g in geo)
    result = {
        'audit_tool': 'CurbOS M0-08 v1',
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_urls': URLS,
        'source_files': {'zones': zfile, 'policies': pfile},
        'source_metadata': {
            'zones': {key: zroot.get(key) for key in ('version','last_updated','time_zone','author')},
            'policies': {key: proot.get(key) for key in ('version','last_updated','time_zone','author')},
        },
        'discovered_paths': {'zones': zpaths, 'policies': ppaths},
        'zone_integrity': {
            'total_rows': len(zones), 'non_null_ids': len(zid_nonnull),
            'duplicate_id_rows': len(zid_nonnull)-len(set(zid_nonnull)),
            'missing_ids': len(ids)-len(zid_nonnull),
            'geometry_types': dict(zone_types),
            'missing_geometry': sum(g is None for g in geo),
        },
        'policy_integrity': {
            'total_rows': len(policies), 'non_null_ids': len(pid_nonnull),
            'duplicate_id_rows': len(pid_nonnull)-len(set(pid_nonnull)),
            'missing_ids': len(policy_ids)-len(pid_nonnull),
            'rules_count': rules_count,
            'activities_by_rule_count': dict(activities),
            'user_classes_storage_types': dict(user_class_forms),
            'user_classes_by_rule_count': dict(user_classes),
        },
        'zone_policy_linkage': {
            'zones_total_denominator': len(zones),
            'zones_with_any_reference': with_refs,
            'zones_with_all_references_resolved': fully_resolved,
            'zones_with_unknown_references': unknown_refs_zones,
            'zones_without_references': len(zones)-with_refs,
            'distinct_referenced_policy_ids': len(distinct_refs),
            'distinct_missing_policy_ids': len(missing_refs),
            'missing_policy_id_examples_max_20': missing_refs[:20],
            'zone_coverage_fraction': round(fully_resolved/len(zones),6) if zones else None,
            'ref_count_distribution': dict(Counter(str(len(r)) for r in refs_by_zone)),
        },
        'review_examples': [
            {'zone_id': get_zone_id(z), 'referenced_policy_ids': get_zone_policy_refs(z),
             'geometry_type': (zone_geometry(z) or {}).get('type')}
            for z in zones[:15]
        ],
        'warnings': [
            'Join rate is a referential-integrity statistic, NOT legal parking coverage.',
            'This tool does not evaluate completeness, permit rules, street signs, legal precedence or full-stay eligibility.',
            'No zero rate / undesignated activity is treated as legal free parking.',
            'Geometry type checks do not verify shape validity, right/left street side, topology or coordinate precision.',
            'This source is a historical snapshot and is not proof of current November 2026 curb laws.',
            'No official occupancy freshness or residential free-parking rate is derived by this tool.',
        ]
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf8')
    print(f'Wrote {a.out}; zones={len(zones)}, policies={len(policies)}, linked={fully_resolved}/{len(zones)}')
    if not with_refs:
        print('WARNING: no zone policy references detected; inspect actual schema before using join metrics.', file=sys.stderr)


if __name__ == '__main__':
    main()
