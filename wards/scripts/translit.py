"""Add English transliterations to extracted voters and write data/voters.json + CSV.
Usage: python3 translit.py raw_voters.json ../data
"""
import json, re, sys, csv, os
V = {'అ':'a','ఆ':'aa','ఇ':'i','ఈ':'ee','ఉ':'u','ఊ':'oo','ఋ':'ru','ఎ':'e','ఏ':'e','ఐ':'ai','ఒ':'o','ఓ':'o','ఔ':'au'}
M = {'ా':'aa','ి':'i','ీ':'ee','ు':'u','ూ':'oo','ృ':'ru','ె':'e','ే':'e','ై':'ai','ొ':'o','ో':'o','ౌ':'au'}
C = {'క':'k','ఖ':'kh','గ':'g','ఘ':'gh','ఙ':'n','చ':'ch','ఛ':'chh','జ':'j','ఝ':'jh','ఞ':'n','ట':'t','ఠ':'th','డ':'d','ఢ':'dh','ణ':'n',
     'త':'t','థ':'th','ద':'d','ధ':'dh','న':'n','ప':'p','ఫ':'ph','బ':'b','భ':'bh','మ':'m','య':'y','ర':'r','ఱ':'r','ల':'l','ళ':'l',
     'వ':'v','శ':'s','ష':'sh','స':'s','హ':'h','ౘ':'ts','ౙ':'dz'}

def tl(s):
    s = re.sub(r'ం(?=\s|$)', 'మ్', s)  # word-final anusvara -> m
    out = []; i = 0
    while i < len(s):
        ch = s[i]; nx = s[i+1] if i+1 < len(s) else ''
        if ch in C:
            out.append(C[ch])
            if nx == '్': i += 2; continue
            if nx in M: out.append(M[nx]); i += 2; continue
            out.append('a'); i += 1; continue
        if ch in V: out.append(V[ch])
        elif ch == 'ం': out.append('m' if nx in ('ప','బ','మ','భ','ఫ') else 'n')
        elif ch == 'ః': out.append('h')
        elif ch in M or ch == '్': pass
        else: out.append(ch)
        i += 1
    w = ''.join(out).replace('aa','a').replace('ee','i').replace('oo','u')
    return w.title()

if __name__ == '__main__':
    src = sys.argv[1] if len(sys.argv) > 1 else 'raw_voters.json'
    outdir = sys.argv[2] if len(sys.argv) > 2 else '../data'
    keys = ['sno','part','part_sno','name','name_en','rel_type','rel_name','rel_en','age','gender','house','epic','page']
    rows = []
    for x in json.load(open(src)):
        x['name_en'] = tl(x['name']); x['rel_en'] = tl(x['rel_name'])
        if not x['rel_type']: x['rel_type'] = '—'   # relation label blank in the source roll
        rows.append({k: x[k] for k in keys})
    json.dump(rows, open(os.path.join(outdir, 'voters.json'), 'w'), ensure_ascii=False, separators=(',',':'))
    with open(os.path.join(outdir, 'ward62_voters.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Ward S.No','Part (Vibhagam)','Assembly Roll S.No','Name (Telugu)','Name (English, transliterated)','Relation',
                    'Relative name (Telugu)','Relative name (English)','Age','Gender','House No','Voter ID (EPIC)','PDF page'])
        for x in rows: w.writerow([x[k] for k in keys])
    print(len(rows), 'voters written to', outdir)
