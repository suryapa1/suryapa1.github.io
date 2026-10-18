#!/usr/bin/env python3
"""Extract one AP SEC municipal ward photo-voter-list PDF into data/wards/<ward>.json.

Usage:  python3 process_ward.py WARD.pdf [WARD2.pdf ...] --out ../data/wards
Needs:  poppler-utils (pdftotext), pdfplumber

Everything comes from the PDF itself: the ward number, assembly, parts and locality
table are read from the cover sheet, and the extracted voter boxes are checked against
the cover-sheet totals (overall, by gender and by part). The result is written to
<ward>.json and summarised in index.json.
"""
import argparse, html, json, os, re, subprocess, sys, tempfile
from collections import Counter
from multiprocessing import Pool

import pdfplumber
from translit import tl

WRE = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
REL = {'తండ్రి': 'Father', 'భర్త': 'Husband', 'తల్లి': 'Mother', 'ఇతరులు': 'Other'}
GEN = {'పు': 'M', 'స్త్రీ': 'F', 'ఇ': 'O'}
COLS = ['sno', 'part', 'part_sno', 'name', 'name_en', 'rel_type', 'rel_name', 'rel_en',
        'age', 'gender', 'house', 'epic', 'page']


# ---------------------------------------------------------------- text helpers
REF_COL_X = (31.064, 210.886, 390.707)   # x of the 3 voter-box columns on the reference roll (ward 62)
REF_TOP_Y = 54.411                        # y of the first box row on the reference roll
REF_COVER = (77.838, 367.300)             # x of the cover-table headers 'వరుస' and 'పురుషులు'
XFS = []                                  # per-page (scale, x offset, y offset)


def _raw_pages(pdf_path):
    tmp = os.path.join(tempfile.mkdtemp(), 'bbox.html')
    subprocess.run(['pdftotext', '-bbox', pdf_path, tmp], check=True)
    pages = re.findall(r'<page[^>]*>(.*?)</page>', open(tmp, encoding='utf-8').read(), re.S)
    return [[dict(x0=float(a), y0=float(b), x1=float(c), y1=float(d), t=html.unescape(t))
             for a, b, c, d, t in WRE.findall(p)] for p in pages]


def _cluster(vals, gap):
    vals = sorted(vals)
    groups = [[vals[0]]]
    for v in vals[1:]:
        if v - groups[-1][-1] <= gap:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def _box_headers(ws):
    out = []
    for w in ws:
        if w['t'].startswith('వార్డు.ఓ.జా') or (w['t'] == 'వార్డు' and any(
                o['t'].startswith('.ఓ.జా') and abs(o['y1'] - w['y1']) < 3 and 0 <= o['x0'] - w['x1'] < 5 for o in ws)):
            out.append(w)
    return out


def page_transform(ws):
    """Fit scale + offsets that map this page onto the reference layout.
    Voter pages: the 3 columns of box headers. Cover pages: the locality-table headers.
    Returns (xf, ncols) or (None, 0) when the page has no usable anchors."""
    hdr = _box_headers(ws)
    if hdr:
        h = sorted(w['y1'] - w['y0'] for w in hdr)[len(hdr) // 2]
        cols = _cluster([w['x0'] for w in hdr], gap=h * 4)
        if len(cols) >= 2:
            k = min(len(cols), 3)
            a = (REF_COL_X[k - 1] - REF_COL_X[0]) / (cols[k - 1] - cols[0])
            b = REF_COL_X[0] - a * cols[0]
            c = REF_TOP_Y - a * min(w['y0'] for w in hdr)
            return (a, b, c), len(cols)
    v = [w for w in ws if w['t'] == 'వరుస']
    m = [w for w in ws if w['t'] == 'పురుషులు']
    if v and m and m[0]['x0'] > v[0]['x0']:
        a = (REF_COVER[1] - REF_COVER[0]) / (m[0]['x0'] - v[0]['x0'])
        return (a, REF_COVER[0] - a * v[0]['x0'], 0.0), 0
    return None, 0


def bbox_pages(pdf_path):
    global XFS
    raw = _raw_pages(pdf_path)
    fits = [page_transform(ws) for ws in raw]
    voter = [f for f, n in fits if f and n >= 2]
    if voter:   # fallback for odd pages (e.g. a last page with a single box)
        med = sorted(voter)[len(voter) // 2]
    else:
        med = (1.0, 0.0, 0.0)
    first_voter = next((i for i, (f, n) in enumerate(fits) if n >= 2), len(fits))
    cover_xf = next((f for f, n in fits[:first_voter] if f), None)
    XFS = [f or (cover_xf if i < first_voter and cover_xf else med) for i, (f, _) in enumerate(fits)]
    ncols = max([n for _, n in fits] or [0])
    out = []
    for ws, (a, b, c) in zip(raw, XFS):
        page = []
        for w in ws:
            x0, x1, y0, y1 = a * w['x0'] + b, a * w['x1'] + b, a * w['y0'] + c, a * w['y1'] + c
            if y1 - y0 > 20:          # big diagonal watermark letters
                continue
            page.append(dict(x0=x0, y0=y0, x1=x1, y1=y1, t=w['t']))
        out.append(page)
    return out, ncols


def space_glyphs(pdf, i):
    """Explicit space characters = true word boundaries (Skia splits Telugu clusters)."""
    a, b, c0 = XFS[i]
    return [(a * c['x0'] + b, a * c['top'] + c0, a * c['bottom'] + c0) for c in pdf.pages[i].chars
            if c['text'] == ' ' and c['size'] * a < 20]


def join_tokens(toks, spaces):
    toks = sorted(toks, key=lambda w: w['x0'])
    s = toks[0]['t']
    for p, n in zip(toks, toks[1:]):
        yc = (n['y0'] + n['y1']) / 2
        real = any(p['x1'] - 1.0 <= sx <= n['x0'] + 1.0 and st - 3 <= yc <= sb + 3 for sx, st, sb in spaces)
        s += (' ' if real or n['x0'] - p['x1'] > 6 else '') + n['t']
    return s


def to_lines(words, spaces, tol=2.5):
    words = sorted(words, key=lambda w: ((w['y0'] + w['y1']) / 2, w['x0']))
    lines, cur, cy = [], [], None
    for w in words:
        yc = (w['y0'] + w['y1']) / 2
        if cy is None or abs(yc - cy) <= tol:
            cur.append(w); cy = yc if cy is None else cy
        else:
            lines.append((cy, cur)); cur, cy = [w], yc
    if cur:
        lines.append((cy, cur))
    return [(y, join_tokens(ws, spaces), ws) for y, ws in lines]


# ---------------------------------------------------------------- cover sheet
def parse_cover(pages_words, pdf):
    meta = {'localities': []}
    first = next((i for i in range(len(pages_words)) if _box_headers(pages_words[i])), 2)
    sp0 = space_glyphs(pdf, 0)
    lines0 = to_lines(pages_words[0], sp0)
    labels = {'జిల్లా పేరు': 'district', 'నగర పాలక సంస్థ పేరు': 'corporation', 'వార్డు సంఖ్య': 'ward',
              'శాసనసభ నియోజకవర్గం సంఖ్య మరియు పేరు': 'assembly', 'విభాగముల వివరములు': 'parts',
              'మొత్తం ఓటర్లు': 'total'}
    for _, l, ws in lines0:
        for lab, key in labels.items():
            if l.startswith(lab) and key not in meta:
                val = join_tokens([w for w in ws if w['x0'] > 330], sp0).strip() if any(w['x0'] > 330 for w in ws) else ''
                meta[key] = re.sub(r'^పేరు\s*', '', val)
    meta['corp_title'] = next((l for _, l, _ in lines0 if re.search(r'[\u0C00-\u0C7F]', l)), '')

    # locality table rows (may continue on following cover pages)
    totals = None
    for pi in range(first):
        sp = space_glyphs(pdf, pi)
        ws = [w for w in pages_words[pi]]
        anchors = sorted([w for w in ws if 80 <= w['x0'] <= 100 and re.fullmatch(r'\d+', w['t'])], key=lambda w: w['y0'])
        for k, a in enumerate(anchors):
            ya = (a['y0'] + a['y1']) / 2
            lo = ya - 10.5
            hi = ya + 10.5
            band = [w for w in ws if lo <= (w['y0'] + w['y1']) / 2 <= hi and w is not a]
            col = lambda x0, x1: sorted([w for w in band if x0 <= w['x0'] < x1], key=lambda w: (round((w['y0'] + w['y1']) / 2), w['x0']))
            num = lambda x0, x1: next((int(w['t']) for w in col(x0, x1) if re.fullmatch(r'\d+', w['t'])), None)
            loc_ws = col(105, 226)
            loc = ' '.join(l for _, l, _ in to_lines(loc_ws, sp, tol=3)) if loc_ws else ''
            frm = ''.join(w['t'] for w in col(226, 266))
            to = ''.join(w['t'] for w in col(266, 306))
            meta['localities'].append(dict(n=int(a['t']), locality=loc, house_from=frm, house_to=to,
                                           part=num(306, 360), male=num(360, 410), female=num(410, 445),
                                           other=num(445, 485), total=num(485, 540)))
        # grand total row
        for _, l, lw in to_lines(ws, sp):
            if re.search(r'మొ\s*త్తం\s*ఓట', l) and not l.startswith('మొత్తం ఓటర్లు ') or ('ఓట' in l and re.search(r'\d{3,}', l) and any(w['x0'] > 470 for w in lw) and 'మొ' in l):
                nums = [int(w['t']) for w in sorted(lw, key=lambda w: w['x0']) if re.fullmatch(r'\d+', w['t']) and w['x0'] > 360]
                if len(nums) == 4:
                    totals = dict(zip(['male', 'female', 'other', 'total'], nums))
    meta['cover_totals'] = totals
    meta['first_voter_page'] = first
    m = re.search(r'\d+', meta.get('ward', ''))
    meta['ward'] = int(m.group()) if m else None
    meta['total'] = int(re.sub(r'\D', '', meta.get('total', '') or '0') or 0)
    meta['parts'] = ', '.join(re.findall(r'\d+', meta.get('parts', '') or ''))
    return meta


# ---------------------------------------------------------------- voter boxes
def clean_val(v):
    return v.strip().lstrip(':').strip()


def parse_box(lines):
    r = dict(sno=None, part=None, part_sno=None, name='', rel_type='', rel_name='', age=None,
             gender='', house='', epic='', assembly=None)
    m = re.search(r'వ\.సం\.\s*\.?\s*(\d+)', lines[0][1])
    if m: r['sno'] = int(m.group(1))
    m = re.search(r'\.(\d+)\s*-\s*(\d+)\s*-\s*(\d+)', lines[0][1])
    if m: r['assembly'], r['part'], r['part_sno'] = map(int, m.groups())
    vals = dict(name=[], rel=[], age=[], house=[], epic=[])
    order = ['name', 'rel', 'age', 'house', 'epic']
    cur = None
    for _, l in lines[1:]:
        l = re.sub(r'\b(Photo|Available)\b', ' ', l).strip()
        if not l:
            continue
        mg = (re.search(r'ింగము\s*:\s*(పు|స్త్రీ|ఇ)', l) or re.search(r'ింగము[^:]{0,30}:\s*(స్త్రీ|పు|ఇ)', l)
              or re.search(r'ింగము.*?(స్త్రీ|పు)\s*$', l))
        if mg: r['gender'] = GEN[mg.group(1)]
        mm = re.match(r'(తండ్రి|భర్త|తల్లి|ఇతరులు)\s*పేరు', l)
        mn = re.match(r'ఓటరు\S{0,3}\s*పేరు', l)
        if mn:
            cur, v = 'name', l[mn.end():]
        elif mm:
            r['rel_type'] = REL[mm.group(1)]; cur, v = 'rel', l[mm.end():]
        elif l.startswith('వయస్సు'):
            cur, v = 'age', re.sub(r'(?:ల)?ింగము.*', '', l[len('వయస్సు'):])
            # an over-long relative name sometimes overprints the age line: move it back
            stray = re.sub(r'[\d:\s]', '', re.sub(r'(?:ల)?ింగము.*', '', l[len('వయస్సు'):]))
            if stray and re.search(r'[\u0C00-\u0C7F]', stray) and vals['rel']:
                vals['rel'].append(stray); r['overlap_fix'] = True
        elif l.startswith('ఇంటి సంఖ్య'):
            cur, v = 'house', l[len('ఇంటి సంఖ్య'):]
        elif 'ఐడి' in l:
            cur, v = 'epic', re.sub(r'.*నెం\.?', '', l)
        elif l.startswith(':'):
            cur, v = next((f for f in order if not vals[f]), cur), l
        else:
            v = l                                   # wrapped continuation line
        v = clean_val(v)
        if v and cur:
            vals[cur].append(v)
    r['name'] = ' '.join(vals['name'])
    r['rel_name'] = ' '.join(vals['rel'])
    a = re.search(r'\d+', ' '.join(vals['age']))
    r['age'] = int(a.group()) if a else None
    r['house'] = ' '.join(vals['house'])
    e = re.search(r'[A-Z]{2,4}[0-9]{6,8}', ' '.join(vals['epic']).replace(' ', ''))
    r['epic'] = e.group() if e else ' '.join(vals['epic'])
    r['rel_type'] = r['rel_type'] or '—'
    return r


_PDF = None
_PAGES = None


def _init(pdf_path, pages, xfs):
    global _PDF, _PAGES, XFS
    _PDF = pdfplumber.open(pdf_path)
    _PAGES = pages
    XFS = xfs


def parse_page(i):
    words, sp = _PAGES[i], space_glyphs(_PDF, i)
    out = []
    for lo, hi in [(0, 205), (205, 385), (385, 600)]:
        cw = [w for w in words if lo <= w['x0'] < hi and 50 < w['y0'] < 800]
        box = None
        for y, l, _ in to_lines(cw, sp):
            if re.match(r'వార్డు\s*\.ఓ\.జా', l):
                if box: out.append(box)
                box = [(y, l)]
            elif box is not None:
                if re.search(r'లెక్కింపు|ప్రచురణ తేదీ|పుట సంఖ్య', l):
                    break
                box.append((y, l))
        if box: out.append(box)
    recs = [parse_box(b) for b in out]
    for r in recs: r['page'] = i + 1
    return recs


def footer_dates(words):
    t = ' '.join(w['t'] for w in words)
    a = re.search(r'లెక్కింపు తేదీ\s*:\s*([\d-]+)', t)
    p = re.search(r'ప్రచురణ తేదీ\s*:\s*([\d-]+)', t)
    return (a.group(1) if a else ''), (p.group(1) if p else '')


# ---------------------------------------------------------------- main
def process(pdf_path, out_dir, workers):
    pages, ncols = bbox_pages(pdf_path)
    pdf = pdfplumber.open(pdf_path)
    meta = parse_cover(pages, pdf)
    first = meta['first_voter_page']
    with Pool(workers, initializer=_init, initargs=(pdf_path, pages, XFS)) as pool:
        recs = [r for chunk in pool.map(parse_page, range(first, len(pages))) for r in chunk]
    recs.sort(key=lambda r: r['sno'] or 0)
    for r in recs:
        r['name_en'] = tl(r['name']); r['rel_en'] = tl(r['rel_name'])
    meta['age_as_of'], meta['published'] = footer_dates(pages[first])
    if not meta['ward']:
        t = ' '.join(w['t'] for w in pages[first])
        m = re.search(r'నె[౦ం]బరు\s*:\s*(\d+)', t) or re.search(r'(\d+)', os.path.basename(pdf_path))
        meta['ward'] = int(m.group(1)) if m else None
    meta['layout'] = dict(scale=round(sorted(x[0] for x in XFS[first:])[len(XFS[first:]) // 2], 4), columns=ncols)

    # ---- validation against the cover sheet
    issues = []
    snos = [r['sno'] for r in recs if r['sno'] is not None]
    if len(snos) < len(recs): issues.append(f'{len(recs) - len(snos)} boxes without a serial number')
    exp_total = (meta['cover_totals'] or {}).get('total') or meta['total']
    missing = sorted(set(range(1, exp_total + 1)) - set(snos))
    dups = [k for k, v in Counter(snos).items() if v > 1]
    if ncols != 3: issues.append(f'expected 3 columns of voter boxes, found {ncols}')
    if missing: issues.append(f'missing serials: {missing[:20]}')
    if dups: issues.append(f'duplicate serials: {dups[:20]}')
    fixed = [r['sno'] for r in recs if r.get('overlap_fix')]
    meta['auto_fixed'] = fixed
    meta['blank_in_source'] = {f: [r['sno'] for r in recs if not r[f]] for f in ['name', 'rel_name'] if any(not r[f] for r in recs)}
    for f in ['age', 'gender', 'house', 'epic']:
        bad = [r['sno'] for r in recs if not r[f] and r[f] != 0]
        if bad: issues.append(f'empty {f}: {bad[:15]}')
    g = Counter(r['gender'] for r in recs)
    ct = meta['cover_totals'] or {}
    got = dict(male=g['M'], female=g['F'], other=g['O'], total=len(recs))
    if ct and got != ct: issues.append(f'gender totals {got} != cover {ct}')
    part_exp = Counter()
    for l in meta['localities']:
        if l['part'] and l['total']: part_exp[l['part']] += l['total']
    part_got = Counter(r['part'] for r in recs)
    if part_exp and dict(part_exp) != dict(part_got):
        issues.append(f'part totals {dict(part_got)} != cover {dict(part_exp)}')
    loc_sum = sum(l['total'] or 0 for l in meta['localities'])
    if ct and loc_sum != ct.get('total'):
        issues.append(f'locality rows sum {loc_sum} != cover total {ct.get("total")}')
    meta['counts'] = got
    meta['issues'] = issues
    meta['source_pdf'] = os.path.basename(pdf_path)
    asm = Counter(r['assembly'] for r in recs).most_common(1)
    meta['assembly_no'] = asm[0][0] if asm else None

    ward = meta['ward']
    os.makedirs(out_dir, exist_ok=True)
    doc = dict(meta=meta, cols=COLS, rows=[[r[c] for c in COLS] for r in recs])
    with open(os.path.join(out_dir, f'{ward}.json'), 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))
    return meta


def write_index(out_dir):
    idx = []
    for fn in os.listdir(out_dir):
        if re.fullmatch(r'\d+\.json', fn):
            m = json.load(open(os.path.join(out_dir, fn), encoding='utf-8'))['meta']
            idx.append(dict(ward=m['ward'], assembly=m.get('assembly', ''), parts=m.get('parts', ''),
                            total=m['counts']['total'], male=m['counts']['male'], female=m['counts']['female'],
                            other=m['counts']['other'], published=m.get('published', ''),
                            verified=not m['issues'], localities=len(m['localities']),
                            bytes=os.path.getsize(os.path.join(out_dir, fn))))
    idx.sort(key=lambda x: x['ward'])
    json.dump(dict(corporation='ఏలూరు నగర పాలక సంస్థ', wards=idx),
              open(os.path.join(out_dir, 'index.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return idx


def write_links(out_dir):
    """Cross-ward 'possibly related' links: same house number in another ward AND a shared
    family-name word (common given names excluded). Written as <ward>.links.json, loaded only
    when someone clicks a house number."""
    import glob, collections
    def nh(h): return re.sub(r'[^0-9a-z/]', '', h.lower())
    def words(s): return {w for w in re.split(r'[\s.]+', re.sub(r'[\u200b-\u200d]', '', s)) if len(w) >= 2}
    rows, freq = {}, collections.Counter()
    for f in glob.glob(os.path.join(out_dir, '[0-9]*.json')):
        if f.endswith('.links.json'):
            continue
        d = json.load(open(f, encoding='utf-8')); c = d['cols']; w = d['meta']['ward']; asm = d['meta'].get('assembly_no') or 65
        for r in d['rows']:
            r = dict(zip(c, r)); r['ward'] = w; r['asm'] = asm; rows[(w, r['sno'])] = r
            for x in words(r['name']) | words(r['rel_name']):
                freq[x] += 1
    common = {w for w, n in freq.items() if n > 2500}
    byh = collections.defaultdict(list)
    for k, r in rows.items():
        h = nh(r['house'])
        if len(h) >= 3:
            byh[h].append(k)
    out = collections.defaultdict(dict)
    keep = ['sno', 'part', 'part_sno', 'name', 'name_en', 'rel_type', 'rel_name', 'rel_en', 'age', 'gender', 'house', 'epic', 'page']
    for h, ks in byh.items():
        if len({w for w, _ in ks}) < 2:
            continue
        fam = {k: (words(rows[k]['name']) | words(rows[k]['rel_name'])) - common for k in ks}
        for a in ks:
            for b in ks:
                if a[0] != b[0] and fam[a] & fam[b]:
                    out[a[0]].setdefault(a[1], []).append([b[0]] + [rows[b][x] for x in keep] + [rows[b]['asm']])
    for f in glob.glob(os.path.join(out_dir, '*.links.json')):
        os.remove(f)
    for w, m in out.items():
        with open(os.path.join(out_dir, f'{w}.links.json'), 'w', encoding='utf-8') as fh:
            json.dump(m, fh, ensure_ascii=False, separators=(',', ':'))
    return sum(len(m) for m in out.values())


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('pdfs', nargs='+')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(__file__), '..', 'data', 'wards'))
    ap.add_argument('--workers', type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()
    for p in a.pdfs:
        try:
            m = process(p, a.out, a.workers)
        except Exception as e:
            print(f"ward  ??      -        ({os.path.basename(p)})  FAILED: {type(e).__name__}: {e}", flush=True)
            continue
        status = 'OK ✓' if not m['issues'] else 'CHECK: ' + ' | '.join(m['issues'])
        print(f"ward {str(m['ward']):>3}  {m['counts']['total']:>5} voters  ({os.path.basename(p)})  "
              f"[scale {m['layout']['scale']}]  {status}", flush=True)
    write_index(a.out)
    n = write_links(a.out)
    print(f'cross-ward family links written for {n} voters')
