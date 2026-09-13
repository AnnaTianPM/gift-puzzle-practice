"""Extract the Gateway Gifted complimentary e-book (vector PDF, mixed question layouts).

Every question ends in a row of 3-4 radio bubbles; the bubbles define the option columns.
The config gives each section a layout that says where the stem (the non-option part) is:
  rows     stem row above a horizontal divider line, options below
  side     stem box left of the option zone (options at the same height)
  grid     no stem: the options are the whole question
  pattern  stem row is the row holding the '?' word, options below

usage: python extract_bonus.py <pdf> <book_id> <config.json> [--limit N] [--debug DIR]
"""
import sys, os, re, json
import pymupdf

pdf_path, book_id, cfg_path = sys.argv[1], sys.argv[2], sys.argv[3]
limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
debug_dir = sys.argv[sys.argv.index('--debug') + 1] if '--debug' in sys.argv else None
cfg = json.load(open(cfg_path, encoding='utf-8'))
out_root = os.path.join(os.path.dirname(__file__), '..', 'docs', 'books', book_id)
SCALE = 2.5
doc = pymupdf.open(pdf_path)
HEADER, FOOTER = 60, 60


def fix_digits(t):
    """The PDF's label font maps digits to control characters (chr(19 + d))."""
    return ''.join(str(ord(c) - 19) if 19 <= ord(c) <= 28 else c for c in t)


def page_items(page):
    """Return (bubbles, labels, qmarks, contents, dividers) for a page."""
    H = page.rect.height
    bubbles, contents, dividers = [], [], []
    for dr in page.get_drawings():
        r = dr['rect']
        if r.y1 < HEADER or r.y0 > H - FOOTER:
            continue
        fill = dr.get('fill')
        kinds = [it[0] for it in dr['items']]
        small = 5 < r.width < 14 and 5 < r.height < 14 and abs(r.width - r.height) < 2
        if small and 'l' in kinds and 'c' in kinds and fill and fill[0] > 0.5:
            bubbles.append(r)          # radio bubble: a light gray ring
        elif small and kinds.count('c') == 4 and 'l' not in kinds and not fill and dr.get('color') == (0.0, 0.0, 0.0):
            bubbles.append(r)          # radio bubble drawn as a black outline circle
        elif r.height < 2 and r.width > 250:
            dividers.append(r)
        elif r.width > 3 and r.height > 3:
            contents.append(r)
    for im in page.get_image_info():
        r = pymupdf.Rect(im['bbox'])
        if r.y1 > HEADER and r.y0 < H - FOOTER and r.width > 3 and r.height > 3:
            contents.append(r)
    labels, qmarks = [], []
    for w in page.get_text('words'):
        t = fix_digits(w[4])
        r = pymupdf.Rect(w[:4])
        if r.x0 < 70 and re.fullmatch(r'\d{1,2}\.', t):
            labels.append((int(t[:-1]), r))
        elif t == '?':
            qmarks.append(r)
    # dedupe bubbles drawn twice
    uniq = []
    for b in sorted(bubbles, key=lambda r: (round(r.y0 / 4), r.x0)):
        if not any(abs(b.x0 - u.x0) < 4 and abs(b.y0 - u.y0) < 4 for u in uniq):
            uniq.append(b)
    return uniq, labels, qmarks, contents, dividers


def union(rects):
    r = pymupdf.Rect(rects[0])
    for x in rects[1:]:
        r |= x
    return r


def page_questions(page, layout):
    bubbles, labels, qmarks, contents, dividers = page_items(page)
    rows = []
    for b in sorted(bubbles, key=lambda r: r.y0):
        if rows and abs(rows[-1][-1].y0 - b.y0) < 6:
            rows[-1].append(b)
        else:
            rows.append([b])
    rows = [sorted(r, key=lambda b: b.x0) for r in rows if 2 <= len(r) <= 5]
    # a row missing a bubble (drawn oddly) borrows the column layout of the fullest row on the page
    full = max(rows, key=len) if rows else []
    fixed = []
    for r in rows:
        if len(r) < len(full) and all(any(abs(b.x0 - f.x0) < 12 for f in full) for b in r):
            y = r[0].y0
            r = [pymupdf.Rect(f.x0, y, f.x1, y + f.height) for f in full]
            print('   note: bubble row completed from page layout at y=%d' % y)
        fixed.append(r)
    rows = [r for r in fixed if len(r) >= 3]
    out = []
    prev_bottom = HEADER
    H = page.rect.height
    for row in rows:
        by = row[0].y0
        lab = [l for l in labels if prev_bottom - 4 <= l[1].y0 < by]
        top = min(l[1].y0 for l in lab) - 4 if lab else prev_bottom
        num = lab[0][0] if lab else None
        later = [l[1].y0 for l in labels if l[1].y0 > by]
        next_top = min(later) - 4 if later else H - FOOTER
        cx = [b.x0 + b.width / 2 for b in row]
        pitch = min(cx[i + 1] - cx[i] for i in range(len(cx) - 1))
        bounds = [cx[0] - pitch / 2] + [(cx[i] + cx[i + 1]) / 2 for i in range(len(cx) - 1)] + [cx[-1] + pitch / 2]
        band = [c for c in contents if c.y0 >= top and c.y1 <= by + 2 and c.x0 > 30 and not any(c.intersects(b) and c.width < 20 for b in row)]
        tall = [c for c in contents if c.y0 >= top and c.y0 < next_top and c.y1 <= next_top + 2 and c.x0 > 30]   # side layout: stem box may reach below the bubbles
        qm = [q for q in qmarks if top < q.y0 < next_top]
        # split stem / option zone
        if layout == 'rows':
            div = [d for d in dividers if top < d.y0 < by]
            split_y = div[0].y0 if div else top
            stem = [c for c in band if c.y1 <= split_y + 1]
            optzone = [c for c in band if c.y0 >= split_y - 1]
        elif layout == 'pattern':
            qm = [q for q in qm if q.y0 < by]
            split_y = max(q.y1 for q in qm) + 6 if qm else top
            stem = [c for c in band if c.y0 < split_y and c.y1 <= split_y + 40] + [q + (-30, -30, 30, 30) for q in qm]
            optzone = [c for c in band if c.y0 >= split_y - 2 and c not in stem]
        elif layout == 'side':
            x_zone = bounds[0] - 4
            stem = [c for c in tall if c.x1 <= x_zone + 8 and c.x0 < x_zone] + [q for q in qm if q.x1 <= x_zone]
            optzone = [c for c in band if c.x0 >= x_zone - 8]
        else:
            stem, optzone = [], band
        # option containers (a big frame around all options) are not option content
        optzone = [c for c in optzone if c.width < 1.6 * pitch]
        cols = []
        for i in range(len(row)):
            col = [c for c in optzone if bounds[i] - 6 <= (c.x0 + c.x1) / 2 <= bounds[i + 1] + 6]
            if not col:
                col = [pymupdf.Rect(bounds[i] + 8, by - 60, bounds[i + 1] - 8, by - 4)]
            cols.append(col)
        opts = []
        for i, col in enumerate(cols):
            r = union(col)
            r.x0 = max(r.x0, bounds[i] - 2); r.x1 = min(r.x1, bounds[i + 1] + 2)
            # image tiles carry transparent margins: never reach into a neighbour's drawn content
            if i > 0:
                r.x0 = max(r.x0, max(c.x1 for c in cols[i - 1]) + 2)
            if i + 1 < len(cols):
                r.x1 = min(r.x1, min(c.x0 for c in cols[i + 1]) - 2)
            opts.append(r + (-5, -5, 5, 5))
        # stem: if a big frame spans everything (grid/side) drop it; else union
        stem_rect = union(stem) + (-6, -6, 6, 6) if stem else None
        out.append({'num': num, 'stem': stem_rect, 'options': opts, 'bubbles': row})
        prev_bottom = by + 14
    return out


book = {'id': book_id, 'ext': 'png', 'tests': []}
answers_all = cfg['answers']
count = 0
for ti, t in enumerate(cfg['tests']):
    tdir = os.path.join(out_root, f'test{ti + 1}')
    os.makedirs(tdir, exist_ok=True)
    answers = answers_all[t['answers']].split()[t.get('skip', 0):]
    expl = t.get('explanations', {})
    qs, n = [], 0
    for page_no in range(t['pages'][0], t['pages'][1] + 1):
        page = doc[page_no - 1]
        found = page_questions(page, t['layout'])
        print(f'page {page_no}: {len(found)} questions', [(q['num'], len(q['options']), 'stem' if q['stem'] else '-') for q in found])
        for q in found:
            n += 1
            if q['num'] not in (None, n + t.get('skip', 0)) and q['num'] is not None and q['num'] > 9:
                print(f'  warning: page {page_no} label {q["num"]} counted {n + t.get("skip", 0)}')
            base = f'q{n:02d}'
            if q['stem']:
                page.get_pixmap(matrix=pymupdf.Matrix(SCALE, SCALE), clip=q['stem'], alpha=False).save(os.path.join(tdir, base + '_m.png'))
            for li, r in enumerate(q['options']):
                page.get_pixmap(matrix=pymupdf.Matrix(SCALE, SCALE), clip=r, alpha=False).save(os.path.join(tdir, f'{base}_{"abcde"[li]}.png'))
            qs.append({'n': n, 'answer': answers[n - 1] if n - 1 < len(answers) else None,
                       'explanation': expl.get(str(n), ''), 'page': page_no, 'nopts': len(q['options']), 'stem': bool(q['stem'])})
            count += 1
            if limit and count >= limit:
                break
        if debug_dir:
            os.makedirs(debug_dir, exist_ok=True)
            shape = page.new_shape()
            for q in found:
                if q['stem']:
                    shape.draw_rect(q['stem']); shape.finish(color=(0, 0.6, 0), width=2)
                for r in q['options']:
                    shape.draw_rect(r); shape.finish(color=(1, 0, 0), width=1.5)
            shape.commit()
            page.get_pixmap(dpi=80).save(os.path.join(debug_dir, f'p{page_no:02d}.png'))
        if limit and count >= limit:
            break
    print(f'{t["name"]}: {n} questions, {len(answers)} answers')
    book['tests'].append({'name': t['name'], 'dir': os.path.basename(tdir), 'prompt': t.get('prompt', ''), 'questions': qs})
    if limit and count >= limit:
        break

with open(os.path.join(out_root, 'book.json'), 'w', encoding='utf-8') as f:
    json.dump(book, f, ensure_ascii=False, indent=1)
with open(os.path.join(out_root, 'book.js'), 'w', encoding='utf-8') as f:
    f.write('window.NNAT_BOOKS = window.NNAT_BOOKS || {};\nwindow.NNAT_BOOKS[' + json.dumps(book_id) + '] = ' + json.dumps(book, ensure_ascii=False) + ';\n')
print('wrote', count, 'questions to', out_root)
