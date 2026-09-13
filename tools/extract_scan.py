"""Extract NNAT questions from a SCANNED Gateway Gifted book (no text layer).

Each PDF page is a two-page spread scanned sideways. After rotating, each book page holds
two questions stacked vertically: a large matrix box, then a row of five option boxes with
answer bubbles underneath. Boxes are found by their dark outlines with OpenCV.

usage: python extract_scan.py <pdf> <book_id> <config.json> [--limit N] [--debug DIR]

config.json:
{
  "rotate": 90,                       # rotation that makes the spread upright
  "dpi": 200,
  "tests": [ {"name": "Practice Test 1", "pages": [9, 21], "answers": "E D B C A ..."} ],
  "skip_pages": [],                   # pdf pages inside the ranges that hold no questions
  "explanations": {"1": {"4": "Note the kind of shape ..."}}   # optional, per test index
}
Question numbering runs through each test in reading order: left page top, left page
bottom, right page top, right page bottom.
"""
import sys, os, json
import numpy as np
import cv2
import pymupdf

pdf_path, book_id, cfg_path = sys.argv[1], sys.argv[2], sys.argv[3]
limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
debug_dir = sys.argv[sys.argv.index('--debug') + 1] if '--debug' in sys.argv else None
dry = '--dry' in sys.argv   # only report how many questions are found per page
cfg = json.load(open(cfg_path, encoding='utf-8'))
out_root = os.path.join(os.path.dirname(__file__), '..', 'docs', 'books', book_id)
DPI = cfg.get('dpi', 200)
ROT = cfg.get('rotate', 90)
S = DPI / 72.0
OUT_SCALE = cfg.get('out_scale', 0.75)   # crops are saved at DPI*OUT_SCALE as JPEG
JPG_Q = cfg.get('jpg_quality', 85)

doc = pymupdf.open(pdf_path)


def render(page_no):
    pix = doc[page_no - 1].get_pixmap(matrix=pymupdf.Matrix(S, S).prerotate(ROT), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    return img


def find_boxes(img):
    """Return list of (x, y, w, h) for rectangles drawn with an outline (dark or faint gray)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    dark = (gray < 110).astype(np.uint8) * 255
    # faint gray outlines: threshold relative to the local background
    faint = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 12)
    mask = cv2.bitwise_or(dark, faint)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    H, W = gray.shape
    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w < 0.35 * DPI or h < 0.25 * DPI:
            continue
        if w > 0.38 * W or h > 0.45 * H:          # page folds / spine shadows
            continue
        if cv2.contourArea(c) < 0.6 * w * h:      # must trace a frame, not a squiggle
            continue
        boxes.append((x, y, w, h))
    boxes.sort(key=lambda b: -(b[2] * b[3]))
    keep = []
    for b in boxes:
        x, y, w, h = b
        if any(abs(x - k[0]) < 0.08 * DPI and abs(y - k[1]) < 0.08 * DPI and abs(w - k[2]) < 0.15 * DPI and abs(h - k[3]) < 0.15 * DPI for k in keep):
            continue
        keep.append(b)
    return keep


def complete_row(bx, half_x0, half_x1):
    """Given 4 or 5 option boxes of one row, return 5 boxes; a missing one (faint outline
    not detected) is inferred from the regular spacing."""
    bx = sorted(bx, key=lambda b: b[0])
    if len(bx) == 5:
        return bx
    if len(bx) != 4:
        return None
    w = int(np.median([b[2] for b in bx])); h = int(np.median([b[3] for b in bx])); y = int(np.median([b[1] for b in bx]))
    cs = [b[0] + b[2] / 2 for b in bx]
    gaps = [cs[i + 1] - cs[i] for i in range(3)]
    pitch = min(gaps)
    if pitch < 0.9 * w:
        return None
    # find the one gap that is ~2 pitches, or add at either end
    for i, g in enumerate(gaps):
        if abs(g - 2 * pitch) < 0.25 * pitch:
            cx = cs[i] + pitch
            break
    else:
        if all(abs(g - pitch) < 0.25 * pitch for g in gaps):
            left, right = cs[0] - pitch, cs[-1] + pitch
            cx = left if left - w / 2 > half_x0 + 0.02 * (half_x1 - half_x0) and (right + w / 2 > half_x1 - 0.02 * (half_x1 - half_x0)) else right
            if left - w / 2 > half_x0 and right + w / 2 < half_x1:
                # both fit: choose the side that keeps the row centred in the half page
                mid = (half_x0 + half_x1) / 2
                cx = left if abs((left + cs[-1]) / 2 - mid) < abs((cs[0] + right) / 2 - mid) else right
        else:
            return None
    bx.append((int(cx - w / 2), y, w, h))
    return sorted(bx, key=lambda b: b[0])


def group_questions(boxes, page_w, page_h, img=None):
    """Group boxes into questions. Each question is a run of five evenly spaced option
    boxes plus the matrix above it (one big frame, or a grid of small boxes). Option rows
    are found by y-clustering then splitting on large horizontal gaps, so a spread whose
    scan is shifted sideways (two pages not centred on the image) still splits correctly."""
    def inside(a, b):
        return a[0] >= b[0] - 4 and a[1] >= b[1] - 4 and a[0] + a[2] <= b[0] + b[2] + 4 and a[1] + a[3] <= b[1] + b[3] + 4 and a != b
    boxes = [a for a in boxes if not any(inside(a, b) for b in boxes)]
    opts = [b for b in boxes if 0.5 * DPI <= b[2] <= 1.6 * DPI and 0.3 * DPI <= b[3] <= 1.4 * DPI]
    clusters = []
    for b in sorted(opts, key=lambda b: b[1]):
        cy = b[1] + b[3] / 2
        for c in clusters:
            if abs(c['cy'] - cy) < 0.4 * DPI:
                c['boxes'].append(b)
                break
        else:
            clusters.append({'cy': cy, 'boxes': [b]})
    # Option frames whose outline merged with a shape poking out of the box sit a little
    # higher or lower than their neighbours. Merge nearby clusters whose boxes interleave
    # horizontally without overlapping (a grid's rows overlap column-wise, so they stay apart).
    def h_overlap(a, b):
        return min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]) > 0.2 * min(a[2], b[2])
    merged = True
    while merged:
        merged = False
        clusters.sort(key=lambda c: c['cy'])
        for i in range(len(clusters) - 1):
            a, b = clusters[i], clusters[i + 1]
            if b['cy'] - a['cy'] < 0.75 * DPI and not any(h_overlap(x, y) for x in a['boxes'] for y in b['boxes']):
                a['boxes'] += b['boxes']
                a['cy'] = float(np.mean([bb[1] + bb[3] / 2 for bb in a['boxes']]))
                del clusters[i + 1]
                merged = True
                break
    rows = []
    for c in clusters:
        bx = sorted(c['boxes'], key=lambda b: b[0])
        # split the cluster into runs at gaps wider than ~2 box widths
        runs, cur = [], [bx[0]]
        for a, b in zip(bx, bx[1:]):
            if b[0] - (a[0] + a[2]) > 1.6 * max(a[2], b[2]):
                runs.append(cur); cur = [b]
            else:
                cur.append(b)
        runs.append(cur)
        # Rows of the left and right page can touch across the spine (the spine gap is often
        # narrower than the gap between options). Split long runs where both parts have the
        # most even spacing.
        def even_split(run):
            if len(run) <= 5:
                return [run]
            cs = [b[0] + b[2] / 2 for b in run]
            def irregular(part):
                # gaps equal to the row pitch, or twice it (one faint box missed), are regular
                gaps = [part[k + 1] - part[k] for k in range(len(part) - 1)]
                if len(gaps) < 2:
                    return 0
                pitch = float(np.median(gaps))
                return sum(1 for g in gaps if not (abs(g - pitch) < 0.25 * pitch or abs(g - 2 * pitch) < 0.25 * pitch))
            best = None
            for i in range(1, len(run)):
                score = irregular(cs[:i]) + irregular(cs[i:])
                if not (i == 5 or len(run) - i == 5):
                    score += 0.5          # prefer peeling off a full row of five
                if best is None or score < best[0]:
                    best = (score, i)
            i = best[1]
            return even_split(run[:i]) + even_split(run[i:])
        runs = [r for run in runs for r in even_split(run)]
        for run in runs:
            x0 = run[0][0] - 0.8 * DPI; x1 = run[-1][0] + run[-1][2] + 0.8 * DPI
            full = complete_row(run, x0, x1)
            if not full:
                continue
            span = full[-1][0] + full[-1][2] - full[0][0]
            if span < 0.28 * page_w:
                continue
            rows.append({'top': min(b[1] for b in full), 'bottom': max(b[1] + b[3] for b in full),
                         'x0': full[0][0], 'x1': full[-1][0] + full[-1][2], 'boxes': full, 'inferred': len(run) == 4})
    if os.environ.get('DEBUG_ROWS'):
        for c in clusters:
            print('   cluster cy=%.0f n=%d xs=%s' % (c['cy'], len(c['boxes']), sorted(int(b[0]) for b in c['boxes'])))
        for r in rows:
            print('   row top=%d x=%d..%d inferred=%s' % (r['top'], r['x0'], r['x1'], r['inferred']))
    opt_boxes = {b for r in rows for b in r['boxes']}
    questions = []
    for r in sorted(rows, key=lambda r: r['top']):
        cx0, cx1 = r['x0'] - 0.15 * (r['x1'] - r['x0']), r['x1'] + 0.15 * (r['x1'] - r['x0'])
        overlap = lambda b: min(b[0] + b[2], cx1) - max(b[0], cx0) > 0.5 * b[2]
        prev_bottom = 0.015 * page_h      # matrices can start right under the running header
        for o in rows:
            if o is not r and o['bottom'] <= r['top'] and min(o['x1'], cx1) - max(o['x0'], cx0) > 0.3 * (r['x1'] - r['x0']):
                prev_bottom = max(prev_bottom, o['bottom'] + 4)
        band = [b for b in boxes if b not in opt_boxes and overlap(b) and b[1] >= prev_bottom and b[1] + b[3] <= r['top'] - 2
                and b[2] >= 0.3 * DPI and b[3] >= 0.3 * DPI]
        if not band:
            continue
        x0 = min(b[0] for b in band); y0 = min(b[1] for b in band)
        x1 = max(b[0] + b[2] for b in band); y1 = max(b[1] + b[3] for b in band)
        limits = (int(cx0 - 0.3 * DPI), int(prev_bottom), int(cx1 + 0.3 * DPI), int(r['top'] - 3))
        m = grow_to_ink(img, (x0, y0, x1 - x0, y1 - y0), limits) if img is not None else (x0, y0, x1 - x0, y1 - y0)
        questions.append({'y': m[1], 'cx': (r['x0'] + r['x1']) / 2, 'matrix': m, 'options': r['boxes'],
                          'parts': len(band), 'inferred': r['inferred']})
    # reading order: page columns left to right (split at the widest horizontal gap), then top to bottom
    xs = sorted(q['cx'] for q in questions)
    split = None
    if len(xs) > 1:
        gaps = [(xs[i + 1] - xs[i], (xs[i + 1] + xs[i]) / 2) for i in range(len(xs) - 1)]
        g, mid = max(gaps)
        if g > 0.25 * page_w:
            split = mid
    for q in questions:
        q['col'] = 0 if split is None or q['cx'] < split else 1
    questions.sort(key=lambda q: (q['col'], q['y']))
    return questions


def grow_to_ink(img, box, limits):
    """Expand a crop rectangle while there is ink touching its edge (shapes drawn outside
    the matrix frames, e.g. spatial-visualisation puzzles), within the given limits."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ink = gray < 185
    x0, y0, w, h = box
    x1, y1 = x0 + w, y0 + h
    lx, ly, ux, uy = limits
    lx, ly = max(0, lx), max(0, ly); ux, uy = min(img.shape[1], ux), min(img.shape[0], uy)
    step = 6
    for _ in range(200):
        grew = False
        if x0 - step >= lx and ink[y0:y1, x0 - step:x0].sum() > 3:
            x0 -= step; grew = True
        if x1 + step <= ux and ink[y0:y1, x1:x1 + step].sum() > 3:
            x1 += step; grew = True
        if y0 - step >= ly and ink[y0 - step:y0, x0:x1].sum() > 3:
            y0 -= step; grew = True
        if y1 + step <= uy and ink[y1:y1 + step, x0:x1].sum() > 3:
            y1 += step; grew = True
        if not grew:
            break
    return (x0, y0, x1 - x0, y1 - y0)


def crop(img, box, pad):
    x, y, w, h = box
    H, W = img.shape[:2]
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
    c = img[y0:y1, x0:x1]
    if OUT_SCALE != 1:
        c = cv2.resize(c, None, fx=OUT_SCALE, fy=OUT_SCALE, interpolation=cv2.INTER_AREA)
    return c


def save(path, im):
    cv2.imwrite(path, im, [cv2.IMWRITE_JPEG_QUALITY, JPG_Q])


book = {'id': book_id, 'ext': 'jpg', 'tests': []}
count = 0


def process_pages(first, last):
    """Yield (page_no, img, question) for every question found on the given pages."""
    for page_no in range(first, last + 1):
        if page_no in cfg.get('skip_pages', []):
            continue
        img = render(page_no)
        boxes = find_boxes(img)
        found = group_questions(boxes, img.shape[1], img.shape[0], img)
        if debug_dir:
            dbg = img.copy()
            for (x, y, w, h) in boxes:
                cv2.rectangle(dbg, (x, y), (x + w, y + h), (0, 0, 255), 3)
            for q in found:
                x, y, w, h = q['matrix']
                cv2.rectangle(dbg, (x, y), (x + w, y + h), (0, 200, 0), 6)
            os.makedirs(debug_dir, exist_ok=True)
            cv2.imwrite(os.path.join(debug_dir, f'p{page_no:02d}.png'), cv2.resize(dbg, None, fx=0.4, fy=0.4))
        print(f'page {page_no}: {len(boxes)} boxes, {len(found)} questions', [(q['parts'], 'i' if q['inferred'] else '') for q in found])
        for q in found:
            yield page_no, img, q


def emit(tdir, n, page_no, img, q):
    base = f'q{n:02d}'
    save(os.path.join(tdir, base + '_m.jpg'), crop(img, q['matrix'], 6))
    for li, b in enumerate(q['options']):
        save(os.path.join(tdir, f'{base}_{"abcde"[li]}.jpg'), crop(img, b, 5))


if 'stream' in cfg:
    # Questions run continuously through the book; split them into tests by count.
    st = cfg['stream']
    per = st['per_test']; skip = st.get('skip_first', 0)
    tests = cfg['tests']
    for ti, t in enumerate(tests):
        os.makedirs(os.path.join(out_root, f'test{ti + 1}'), exist_ok=True)
        t['_qs'] = []
    idx = 0
    for page_no, img, q in process_pages(*st['pages']):
        idx += 1
        if idx <= skip:
            continue
        k = idx - skip - 1
        ti, n = k // per, k % per + 1
        if ti >= len(tests):
            print(f'  extra question found on page {page_no} (beyond {len(tests)} x {per}); ignored')
            continue
        if not dry:
            emit(os.path.join(out_root, f'test{ti + 1}'), n, page_no, img, q)
        answers = tests[ti].get('answers', '').split()
        expl = cfg.get('explanations', {}).get(str(ti + 1), {})
        tests[ti]['_qs'].append({'n': n, 'answer': answers[n - 1] if n - 1 < len(answers) else None,
                                 'explanation': expl.get(str(n), ''), 'page': page_no})
        count += 1
        if limit and count >= limit:
            break
    for ti, t in enumerate(tests):
        book['tests'].append({'name': t['name'], 'dir': f'test{ti + 1}', 'questions': t['_qs']})
else:
    for ti, t in enumerate(cfg['tests']):
        answers = t.get('answers', '').split()
        expl = cfg.get('explanations', {}).get(str(ti + 1), {})
        tdir = os.path.join(out_root, f'test{ti + 1}')
        os.makedirs(tdir, exist_ok=True)
        qs = []
        n = 0
        for page_no, img, q in process_pages(*t['pages']):
            n += 1
            if not dry:
                emit(tdir, n, page_no, img, q)
            qs.append({'n': n, 'answer': answers[n - 1] if n - 1 < len(answers) else None,
                       'explanation': expl.get(str(n), ''), 'page': page_no})
            count += 1
            if limit and count >= limit:
                break
        book['tests'].append({'name': t['name'], 'dir': os.path.basename(tdir), 'questions': qs})
        if limit and count >= limit:
            break

with open(os.path.join(out_root, 'book.json'), 'w', encoding='utf-8') as f:
    json.dump(book, f, ensure_ascii=False, indent=1)
with open(os.path.join(out_root, 'book.js'), 'w', encoding='utf-8') as f:
    f.write('window.NNAT_BOOKS = window.NNAT_BOOKS || {};\nwindow.NNAT_BOOKS[' + json.dumps(book_id) + '] = ' + json.dumps(book, ensure_ascii=False) + ';\n')
print('wrote', count, 'questions to', out_root)
