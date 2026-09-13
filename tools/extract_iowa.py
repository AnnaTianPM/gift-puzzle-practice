"""Extract the scanned IOWA Grade 1 practice workbook (Redmond Ridge Montessori).

The PDF holds two-page spreads scanned sideways. Book page b is on PDF page (b+3)//2,
left half when b is odd. Every question ends in answer bubbles (empty circles): either a
horizontal row under the choices, or a vertical column with a word to the right of each
bubble. The question text (meant to be read aloud by a grown-up) plus any picture becomes
the stem image; the choices become option images.

usage: python extract_iowa.py <pdf> <book_id> <config.json> [--debug DIR]
"""
import sys, os, json
import numpy as np
import cv2
import pymupdf

pdf_path, book_id, cfg_path = sys.argv[1], sys.argv[2], sys.argv[3]
debug_dir = sys.argv[sys.argv.index('--debug') + 1] if '--debug' in sys.argv else None
cfg = json.load(open(cfg_path, encoding='utf-8'))
out_root = os.path.join(os.path.dirname(__file__), '..', 'docs', 'books', book_id)
DPI = cfg.get('dpi', 150)
S = DPI / 72.0
doc = pymupdf.open(pdf_path)
_cache = {}


def book_page(b):
    """Render book page b (upright, one page) as a BGR image."""
    if b in _cache:
        return _cache[b]
    # after the 90-degree turn the top half of the scan is the right-hand (odd) book page
    pdf_no = (b + 3) // 2 if b % 2 == 1 else b // 2 + 2
    page = doc[pdf_no - 1]
    r = page.rect
    clip = pymupdf.Rect(0, 0, r.width, r.height / 2) if b % 2 == 1 else pymupdf.Rect(0, r.height / 2, r.width, r.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(S, S).prerotate(90), clip=clip, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    _cache[b] = img
    return img


def find_bubbles(gray):
    """Empty answer circles: small round contours with a hollow centre."""
    dark = (gray < 175).astype(np.uint8) * 255
    contours, _ = cv2.findContours(dark, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    rmin, rmax = 0.055 * DPI, 0.11 * DPI          # diameter 8..16 pt
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if not (2 * rmin <= w <= 2 * rmax and 2 * rmin <= h <= 2 * rmax and abs(w - h) <= 0.3 * w):
            continue
        area = cv2.contourArea(c)
        if area < 0.6 * (np.pi * (w / 2) ** 2):
            continue
        # hollow centre: the middle must be bright
        cx, cy = x + w // 2, y + h // 2
        if gray[cy - 2:cy + 3, cx - 2:cx + 3].mean() < 200:
            continue
        # a bubble stands alone: no ink right next to it (letters in a word always have neighbours)
        m = int(0.5 * w)
        H, W = gray.shape
        lft = gray[y:y + h, max(0, x - m):x] < 170
        rgt = gray[y:y + h, x + w:min(W, x + w + m)] < 170
        if lft.sum() > 8 or rgt.sum() > 8:
            continue
        out.append((cx, cy, w // 2))
    # dedupe (inner/outer contour of the ring)
    keep = []
    for b in sorted(out, key=lambda b: (b[1], b[0])):
        if not any(abs(b[0] - k[0]) < 6 and abs(b[1] - k[1]) < 6 for k in keep):
            keep.append(b)
    return keep


def ink_rows(gray, x0, x1):
    return (gray[:, x0:x1] < 170).sum(axis=1)


def content_box(mask, x0, y0, x1, y1, pad=6):
    """Tight bounding box of ink (True cells of mask) inside a region (or None)."""
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    sub = mask[y0:y1, x0:x1]
    ys = np.where(sub.any(axis=1))[0]
    xs = np.where(sub.any(axis=0))[0]
    if len(ys) == 0 or len(xs) == 0:
        return None
    H, W = mask.shape
    return (max(0, x0 + xs[0] - pad), max(0, y0 + ys[0] - pad), min(W, x0 + xs[-1] + pad + 1), min(H, y0 + ys[-1] + pad + 1))


def page_questions(b):
    img = book_page(b)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    # printable area: skip the spine shadow on the left and the footer
    top, bottom = int(0.05 * H), int(0.935 * H)                  # footer line sits at ~0.94 H
    col_frac = (gray[top:bottom] < 170).mean(axis=0)
    # crop margins: just inside the scanner's spine shadow / page edge (dark down the whole page)
    strong = np.where(col_frac > 0.5)[0]
    left = int(0.05 * W); right = W - 6
    ls = strong[strong < 0.18 * W]; rs = strong[strong > 0.82 * W]
    if len(ls): left = max(left, int(ls.max()) + 10)
    if len(rs): right = min(right, int(rs.min()) - 10)
    # Scanner shadow / page-edge stripes: columns whose (light) ink runs continuously over
    # more than half the page height. Pictures never do that; they are at most ~40% tall.
    soft = gray[top:bottom] < 200
    xs_idx = np.arange(W)
    longest = np.zeros(W, dtype=int)
    for x in np.where(soft.mean(axis=0) > 0.3)[0]:
        col = np.concatenate(([0], soft[:, x].astype(np.int8), [0]))
        edges = np.flatnonzero(np.diff(col))
        if len(edges) >= 2:
            longest[x] = int((edges[1::2] - edges[::2]).max())
    faint = (longest > 0.5 * (bottom - top)) & ((xs_idx < 0.25 * W) | (xs_idx > 0.75 * W))
    ink_full = (gray < 170)
    ink_full[:, faint] = False
    ink_full[:, :int(0.05 * W)] = False
    ink_full[:, int(0.97 * W):] = False              # paper edge
    if faint.any():
        ls = xs_idx[faint & (xs_idx < 0.25 * W)]; rs = xs_idx[faint & (xs_idx > 0.75 * W)]
        if len(ls): left = max(left, int(ls.max()) + 6)
        if len(rs): right = min(right, int(rs.min()) - 6)
    bubbles = [bb for bb in find_bubbles(gray) if 0.08 * W < bb[0] < 0.95 * W and top < bb[1] < bottom]
    if os.environ.get('DEBUG_IOWA'):
        print(f'   page {b}: left={left} right={right} shadow_cols={int(faint.sum())} {list(xs_idx[faint][:3])}..{list(xs_idx[faint][-3:])} bubbles={len(bubbles)}')
    # group: horizontal rows (same y) and vertical columns (same x)
    rows, used = [], set()
    for i, bb in enumerate(sorted(bubbles, key=lambda t: (t[1], t[0]))):
        pass
    bubbles.sort(key=lambda t: (t[1], t[0]))
    groups = []
    for bb in bubbles:
        for g in groups:
            if g['kind'] == 'row' and abs(g['items'][-1][1] - bb[1]) < 0.12 * DPI:
                g['items'].append(bb); break
        else:
            groups.append({'kind': 'row', 'items': [bb]})
    # single bubbles that stack vertically at the same x form a column
    singles = [g for g in groups if len(g['items']) == 1]
    cols = []
    for g in sorted(singles, key=lambda g: g['items'][0][1]):
        bb = g['items'][0]
        for c in cols:
            last = c['items'][-1]
            if abs(last[0] - bb[0]) < 0.15 * DPI and 0.2 * DPI < bb[1] - last[1] < 0.9 * DPI:
                c['items'].append(bb); break
        else:
            cols.append({'kind': 'col', 'items': [bb]})
    groups = [g for g in groups if len(g['items']) >= 3] + [c for c in cols if len(c['items']) >= 3]
    groups.sort(key=lambda g: g['items'][0][1])
    out = []
    prev_bottom = top
    for g in groups:
        items = g['items']
        if g['kind'] == 'row':
            items.sort(key=lambda t: t[0])
            by = min(t[1] for t in items) - items[0][2] - 2            # top of the bubbles
            cx = [t[0] for t in items]
            pitch = min(cx[i + 1] - cx[i] for i in range(len(cx) - 1))
            bounds = [max(left, int(cx[0] - pitch / 2))] + [int((cx[i] + cx[i + 1]) / 2) for i in range(len(cx) - 1)] + [min(right, int(cx[-1] + pitch / 2))]
            # The options are the block(s) of ink above the bubbles. Scanning upward, the zone
            # ends at a blank gap of 14+ rows, or at a smaller gap (6+) that is followed by a
            # line of question text: ink starting at the page's text margin with no wide gaps
            # inside it (option pictures/words are centred in columns with wide gaps between).
            x0 = max(left, int(0.11 * W))
            ink = ink_full[:, x0:right]
            row_ink = ink.sum(axis=1)
            # ignore specks: ink blocks thinner than 3 rows or lighter than 8 px per row
            row_ink[row_ink < 3] = 0
            yy = 0
            while yy < H:
                if row_ink[yy] > 0:
                    y2 = yy
                    while y2 + 1 < H and row_ink[y2 + 1] > 0:
                        y2 += 1
                    if y2 - yy + 1 < 3 or row_ink[yy:y2 + 1].max() < 8:
                        row_ink[yy:y2 + 1] = 0
                    yy = y2 + 1
                else:
                    yy += 1
            firsts = [np.argmax(ink[r]) for r in range(top, bottom) if row_ink[r] > 0]
            margin_x = int(np.percentile(firsts, 3)) if firsts else 0

            def text_line(yb):
                # block of ink rows ending at yb (scanning upward); is it a line of running text?
                yt = yb
                while yt - 1 > prev_bottom and row_ink[yt - 1] > 0:
                    yt -= 1
                proj = ink[yt:yb + 1].any(axis=0)
                xs = np.where(proj)[0]
                if len(xs) == 0 or xs[0] > margin_x + 0.03 * W:
                    return False
                gaps = np.diff(xs)
                return gaps.max() < 0.25 * pitch if len(gaps) else True

            y = by - 4                                  # skip the bubbles' antialiased top edge
            zone_top = prev_bottom
            seen = blank = 0
            rule = 'none'
            while y > prev_bottom:
                if row_ink[y] > 0:
                    if seen and blank >= 14:
                        zone_top = y + blank // 2; rule = 'gap'
                        break
                    if seen and blank >= 6 and text_line(y):
                        zone_top = y + blank // 2; rule = 'text'
                        break
                    seen, blank = 1, 0
                else:
                    blank += 1
                y -= 1
            if os.environ.get('DEBUG_IOWA'):
                print(f'      row group by={by} zone_top={zone_top} rule={rule} margin_x={margin_x + x0}')
            # column boundaries: move each midpoint to the nearest blank column of the option zone,
            # so long answers ('Singing and Reading') are not cut where they nearly touch
            zone = ink_full[zone_top:by - 2, :].any(axis=0)
            runs, start = [], None                      # blank runs (start, end) across the zone
            for x in range(W + 1):
                blank_col = x < W and not zone[x]
                if blank_col and start is None:
                    start = x
                elif not blank_col and start is not None:
                    runs.append((start, x)); start = None
            wide = [r for r in runs if r[1] - r[0] >= 0.08 * pitch]
            snapped = [bounds[0]]
            for m in bounds[1:-1]:
                near = [r for r in wide if r[0] - 0.45 * pitch <= m <= r[1] + 0.45 * pitch]
                if near:
                    r = min(near, key=lambda r: 0 if r[0] <= m <= r[1] else min(abs(m - r[0]), abs(m - r[1])))
                    m = (r[0] + r[1]) // 2
                snapped.append(m)
            snapped.append(bounds[-1])
            bounds = snapped
            bounds[0] = min(bounds[0], max(left, int(cx[0] - 0.9 * pitch)))
            bounds[-1] = max(bounds[-1], min(right, int(cx[-1] + 0.9 * pitch)))
            opts = []
            for i in range(len(items)):
                box = content_box(ink_full, bounds[i] + 1, zone_top, bounds[i + 1] - 1, by - 2)
                if box is None:
                    box = (bounds[i] + 10, by - 40, bounds[i + 1] - 10, by - 4)
                opts.append(box)
            stem = content_box(ink_full, left, prev_bottom, right, zone_top - 1)
            if stem:   # story text can run right up to the spine; keep a little extra on the right
                stem = (stem[0], stem[1], min(W - 2, stem[2] + int(0.025 * W)), stem[3])
            group_bottom = max(t[1] for t in items) + items[0][2] + 4
        else:
            items.sort(key=lambda t: t[1])
            bx = min(t[0] for t in items) - items[0][2]
            step = int(np.median([items[i + 1][1] - items[i][1] for i in range(len(items) - 1)]))
            opts = []
            for t in items:
                y0, y1 = t[1] - step // 2 + 2, t[1] + step // 2 - 2
                box = content_box(ink_full, t[0] + t[2] + 4, y0, right, y1)
                if box is None:
                    box = (t[0] + t[2] + 6, t[1] - 15, t[0] + t[2] + 120, t[1] + 15)
                opts.append(box)
            first_top = items[0][1] - step // 2
            # stem: anything above the first bubble, plus the picture left of the bubble column
            parts = [p for p in (content_box(ink_full, left, prev_bottom, right, first_top - 1),
                                 content_box(ink_full, left, first_top, bx - 8, items[-1][1] + step // 2)) if p]
            stem = None
            if parts:
                stem = (min(p[0] for p in parts), min(p[1] for p in parts), max(p[2] for p in parts), max(p[3] for p in parts))
            group_bottom = max([items[-1][1] + items[-1][2] + 4] + [o[3] for o in opts] + ([stem[3]] if stem else []))
        out.append({'stem': stem, 'options': opts, 'kind': g['kind'], 'y': items[0][1]})
        prev_bottom = min(bottom, group_bottom + (16 if g['kind'] == 'col' else 2))
    return img, out


def crop(img, box):
    x0, y0, x1, y1 = box
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = max(x0 + 2, int(x1)), max(y0 + 2, int(y1))
    return img[y0:y1, x0:x1]


def save(path, im):
    cv2.imwrite(path, im, [cv2.IMWRITE_JPEG_QUALITY, 85])


book = {'id': book_id, 'ext': 'jpg', 'tests': []}
total = 0
for ti, t in enumerate(cfg['tests']):
    tdir = os.path.join(out_root, f'test{ti + 1}')
    os.makedirs(tdir, exist_ok=True)
    answers = t['answers'].split()
    skip = set(tuple(x) for x in t.get('skip', []))          # [book_page, index] pairs to ignore (samples)
    qs, n = [], 0
    for b in range(t['pages'][0], t['pages'][1] + 1):
        img, found = page_questions(b)
        print(f'book page {b}: {len(found)} questions', [(q['kind'], len(q['options']), 'stem' if q['stem'] else '-') for q in found])
        for qi, q in enumerate(found):
            if (b, qi) in skip:
                continue
            n += 1
            base = f'q{n:02d}'
            if q['stem']:
                save(os.path.join(tdir, base + '_m.jpg'), crop(img, q['stem']))
            for li, box in enumerate(q['options']):
                save(os.path.join(tdir, f'{base}_{"abcde"[li]}.jpg'), crop(img, box))
            qs.append({'n': n, 'answer': answers[n - 1] if n - 1 < len(answers) else None, 'explanation': '',
                       'page': b, 'nopts': len(q['options']), 'stem': bool(q['stem'])})
        if debug_dir:
            os.makedirs(debug_dir, exist_ok=True)
            dbg = img.copy()
            for q in found:
                if q['stem']:
                    cv2.rectangle(dbg, q['stem'][:2], q['stem'][2:], (0, 160, 0), 3)
                for box in q['options']:
                    cv2.rectangle(dbg, box[:2], box[2:], (0, 0, 255), 2)
            cv2.imwrite(os.path.join(debug_dir, f'b{b:02d}.png'), cv2.resize(dbg, None, fx=0.5, fy=0.5))
    print(f'{t["name"]}: {n} questions, {len(answers)} answers')
    total += n
    book['tests'].append({'name': t['name'], 'dir': os.path.basename(tdir), 'prompt': t.get('prompt', ''), 'questions': qs})

with open(os.path.join(out_root, 'book.json'), 'w', encoding='utf-8') as f:
    json.dump(book, f, ensure_ascii=False, indent=1)
with open(os.path.join(out_root, 'book.js'), 'w', encoding='utf-8') as f:
    f.write('window.NNAT_BOOKS = window.NNAT_BOOKS || {};\nwindow.NNAT_BOOKS[' + json.dumps(book_id) + '] = ' + json.dumps(book, ensure_ascii=False) + ';\n')
print('wrote', total, 'questions to', out_root)
