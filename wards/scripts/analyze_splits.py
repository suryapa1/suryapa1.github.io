#!/usr/bin/env python3
"""Find households whose members are registered in different wards.

Household  = same full-format door number (3+ parts, e.g. 16a-5-21/2; short numbers like
             6-79 repeat on different streets so they are skipped) + the same surname.
             Surname = word shared by a voter's own name and their relative's name
             (Telugu rolls repeat the family name), else the first/last word of the name;
             very common words (రావు, లక్ష్మి, వెంకట, షేక్ …) never count.
Confidence = 'strong' when, across wards, one member's relative is another member
             (wife -> husband, child -> parent) or two members name the same relative
             (siblings / mother & son); otherwise 'possible' (same door no. + surname).
Home ward  = the ward holding most of the household; the others are 'away' voters, the ones
             a ward-by-ward canvass is likely to miss.

Usage: python3 analyze_splits.py ../data/wards     -> writes ../data/wards/splits.json
"""
import collections, glob, json, os, re, sys

D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'data', 'wards')
ZW = re.compile(r'[​-‍]')


def nh(h):
    return re.sub(r'[^0-9a-z/]', '', h.lower())


def words(s):
    return {w for w in re.split(r'[\s.]+', ZW.sub('', s)) if len(w) >= 2}


SK = re.compile(r'[\u0C3E-\u0C4D\u0C55\u0C56\u0C62\u0C63\u0C01-\u0C03]')


def skel(w):
    """Consonant skeleton so spelling variants meet: నెరుసు = నెర్సు = నేర్సు = నేరుసు -> నరస."""
    return SK.sub('', w)


def surnames(r, common):
    n, rel = words(r['name']) - common, words(r['rel_name']) - common
    both = {skel(w) for w in n} & {skel(w) for w in rel}
    if not both:
        parts = [w for w in re.split(r'[\s.]+', ZW.sub('', r['name'])) if len(w) >= 2 and w not in common]
        both = {skel(parts[0]), skel(parts[-1])} if parts else set()
    if r.get('rel_type') == 'Husband':     # a wife may keep her maiden surname; her husband's carries the family
        hp = [w for w in re.split(r'[\s.]+', ZW.sub('', r['rel_name'])) if len(w) >= 2 and w not in common]
        if len(hp) >= 2:
            both |= {skel(hp[0]), skel(hp[-1])}
    return {x for x in both if len(x) >= 2}


def full_door(h):
    return len([p for p in re.split(r'[-/]', h) if p.strip()]) >= 3 and len(re.findall(r'-', h)) >= 2


def nname(s):
    return re.sub(r'[\s.]', '', ZW.sub('', s))


rows, freq = {}, collections.Counter()
ward_total = {}
for f in glob.glob(os.path.join(D, '[0-9]*.json')):
    if not re.fullmatch(r'\d+\.json', os.path.basename(f)):
        continue
    d = json.load(open(f, encoding='utf-8'))
    c, w = d['cols'], d['meta']['ward']
    ward_total[w] = len(d['rows'])
    for r in d['rows']:
        r = dict(zip(c, r)); r['ward'] = w
        rows[(w, r['sno'])] = r
        for x in words(r['name']) | words(r['rel_name']):
            freq[x] += 1
common = {w for w, n in freq.items() if n > 2500}

# ---- group by door number, then link members that share a family word (union-find)
byh = collections.defaultdict(list)
for k, r in rows.items():
    d = nh(r['house'])
    if not d or not re.search(r'\d', d):
        continue
    # full door numbers are city-wide (can span wards); short ones only group within a ward
    byh[d if full_door(r['house']) else f"{k[0]}#{d}"].append(k)

parent = {}
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]; x = parent[x]
    return x
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb: parent[ra] = rb

families, households = [], []          # all families (2+ voters) / the split ones
for h, ks in byh.items():
    if len(ks) < 2 or len(ks) > 400:   # 400+: placeholder door like "0" or "NA"
        continue
    fam = {k: surnames(rows[k], common) for k in ks}
    for k in ks: parent[k] = k
    for i, a in enumerate(ks):
        for b in ks[i + 1:]:
            if fam[a] & fam[b]:
                union(a, b)
    groups = collections.defaultdict(list)
    for k in ks: groups[find(k)].append(k)
    for g in groups.values():
        if len(g) < 2:
            continue
        wards = collections.Counter(w for w, _ in g)
        split = len(wards) > 1
        W = {k: (words(rows[k]['name']), words(rows[k]['rel_name'])) for k in g}
        def rel_is(a, b):      # a's relative is b
            return (len(W[a][1]) >= 2 and W[a][1] == W[b][0]) or \
                   (len(nname(rows[a]['rel_name'])) >= 6 and nname(rows[a]['rel_name']) == nname(rows[b]['name']))
        def same_rel(a, b):    # a and b name the same relative
            return len(W[a][1]) >= 2 and W[a][1] == W[b][1]
        # split families: the relationship must cross wards; together families: any pair
        strong = any(a != b and (a[0] != b[0] or not split) and (rel_is(a, b) or same_rel(a, b)) for a in g for b in g)
        top = wards.most_common()
        home = top[0][0] if (len(top) == 1 or top[0][1] > top[1][1]) else None   # tie -> no clear home
        sk_top = collections.Counter(x for k in g for x in fam[k]).most_common(1)
        raw = collections.Counter(w for k in g for w in (words(rows[k]['name']) | words(rows[k]['rel_name']))
                                  if sk_top and skel(w) == sk_top[0][0])
        surname = raw.most_common(1)
        f = dict(house=rows[g[0]]['house'], key=h, surname=surname[0][0] if surname else '',
                 strong=strong, home=home, wards=dict(wards), members=sorted(g), split=split)
        families.append(f)
        if split:
            households.append(f)

# ---- per-ward impact and ward-pair flows
away_from = collections.Counter()     # home ward -> members registered elsewhere
away_in = collections.Counter()       # ward holding members whose family is mostly elsewhere
split_hh = collections.Counter()
fam_w, tog_w = collections.Counter(), collections.Counter()
for f in families:
    for w in f['wards']:
        fam_w[w] += 1
        if not f['split']: tog_w[w] += 1
pairs = collections.Counter()
for hh in households:
    for w in hh['wards']:
        split_hh[w] += 1
    if hh['home'] is None:
        continue
    for (w, s) in hh['members']:
        if w != hh['home']:
            away_from[hh['home']] += 1
            away_in[w] += 1
            pairs[(hh['home'], w)] += 1

# ---- possible duplicate registrations
dkey = collections.defaultdict(list)
for k, r in rows.items():
    a, b = nname(r['name']), nname(r['rel_name'])
    if len(a) >= 4 and len(b) >= 4 and r['age']:
        dkey[(a, b)].append(k)
dups = []
for key, ks in dkey.items():
    if len(ks) < 2:
        continue
    ks = sorted(ks, key=lambda k: rows[k]['age'])
    grp = [ks[0]]
    for k in ks[1:]:
        if rows[k]['age'] - rows[grp[0]]['age'] <= 2:
            grp.append(k)
        else:
            if len(grp) > 1: dups.append(grp)
            grp = [k]
    if len(grp) > 1: dups.append(grp)
dups = [g for g in dups if len({rows[k]['epic'] for k in g}) == len(g) or True]
dup_same_door = sum(1 for g in dups if len({nh(rows[k]['house']) for k in g}) == 1)
dup_cross = sum(1 for g in dups if len({k[0] for k in g}) > 1)
dup_ward = collections.Counter(w for g in dups for (w, s) in g)

KEEP = ['sno', 'name', 'name_en', 'rel_type', 'rel_name', 'age', 'gender', 'epic', 'house']
out = dict(
    generated_from=len(ward_total), voters=sum(ward_total.values()),
    summary=dict(
        households=len(households),
        strong=sum(h['strong'] for h in households),
        voters_in_split=sum(len(h['members']) for h in households),
        away_voters=sum(away_from.values()),
        away_voters_strong=sum(1 for h in households if h['home'] and h['strong'] for (w, s) in h['members'] if w != h['home']),
        no_clear_home=sum(1 for h in households if h['home'] is None),
        families_total=len(families), families_together=len(families) - len(households),
        voters_in_families=sum(len(f['members']) for f in families),
        duplicates=len(dups), duplicates_cross_ward=dup_cross, duplicates_same_door=dup_same_door,
        duplicate_extra_entries=sum(len(g) - 1 for g in dups),
    ),
    wards=[dict(ward=w, voters=ward_total[w], split_households=split_hh[w],
                away_from=away_from[w], away_in=away_in[w], dup_entries=dup_ward[w],
                families=fam_w[w], together=tog_w[w]) for w in sorted(ward_total)],
    pairs=[[a, b, n] for (a, b), n in pairs.most_common(60)],
    cols=['ward'] + KEEP,
    households=[dict(h=hh['house'], s=hh['surname'], st=int(hh['strong']), home=hh['home'],
                     m=[[w] + [rows[(w, s)][k] for k in KEEP] for (w, s) in hh['members']])
                for hh in sorted(households, key=lambda x: (-x['strong'], -len(x['members'])))],
    duplicates=[dict(same_door=int(len({nh(rows[k]['house']) for k in g}) == 1),
                     m=[[w] + [rows[(w, s)][k] for k in KEEP] for (w, s) in g])
                for g in sorted(dups, key=lambda g: (-(len({k[0] for k in g}) > 1), -len(g)))],
)
per = collections.defaultdict(list)
for f in families:
    rec = [f['house'], f['surname'], int(f['strong']), f['home'], int(f['split']),
           [[w] + [rows[(w, sn)][k] for k in KEEP] for (w, sn) in f['members']]]
    for w in f['wards']:
        per[w].append(rec)
for w in ward_total:
    with open(os.path.join(D, f'{w}.families.json'), 'w', encoding='utf-8') as fh:
        json.dump(dict(cols=['ward'] + KEEP, families=sorted(per[w], key=lambda r: (-r[4], -len(r[5])))), fh,
                  ensure_ascii=False, separators=(',', ':'))

dst = os.path.join(D, 'splits.json')
with open(dst, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
s = out['summary']
print(f"{s['duplicates']} possible duplicate groups ({s['duplicates_cross_ward']} across wards, {s['duplicates_same_door']} same door, {s['duplicate_extra_entries']} extra entries)")
print(f"{s['families_total']} families of 2+ voters: {s['families_together']} together in one ward, {s['households']} split")
print(f"{s['households']} split households ({s['strong']} strong) · {s['voters_in_split']} voters · "
      f"{s['away_voters']} registered away from their family's ward · wrote {dst} ({os.path.getsize(dst)//1024} KB)")
