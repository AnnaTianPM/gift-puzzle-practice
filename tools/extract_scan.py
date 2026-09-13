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


def group_questions(boxes, page_w, page_h):
    """Group boxes into questions. Each question is a row of five option boxes plus the
    matrix above it. The matrix may be one big frame (pattern completion) or a grid of
    small boxes (analogy 2x2, serial reasoning 3x3), so it is taken as the union of every
    box on the same half of the spread between the previous option row and this one."""
    def inside(a, b):
        return a[0] >= b[0] - 4 and a[1] >= b[1] - 4 and a[0] + a[2] <= b[0] + b[2] + 4 and a[1] + a[3] <= b[1] + b[3] + 4 and a != b
    boxes = [a for a in boxes if not any(inside(a, b) for b in boxes)]
    side_of = lambda b: 0 if b[0] + b[2] / 2 < page_w / 2 else 1
    opts = [b for b in boxes if 0.5 * DPI <= b[2] <= 1.6 * DPI and 0.3 * DPI <= b[3] <= 1.4 * DPI]
    rows = []
    for b in sorted(opts, key=lambda b: b[1]):
        cy = b[1] + b[3] / 2
        for r in rows:
            if r['side'] == side_of(b) and abs(r['cy'] - cy) < 0.4 * DPI:
                r['boxes'].append(b)
                break
        else:
            rows.append({'cy': cy, 'side': side_of(b), 'boxes': [b]})
    good = []
    for r in rows:
        bx = sorted(r['boxes'], key=lambda b: b[0])
        if len(bx) > 5:
            mw = np.median([b[2] for b in bx]); mh = np.median([b[3] for b in bx])
            bx = sorted(bx, key=lambda b: abs(b[2] - mw) + abs(b[3] - mh))[:5]
            bx.sort(key=lambda b: b[0])
        half_x0, half_x1 = (0, page_w / 2) if r['side'] == 0 else (page_w / 2, page_w)
        full = complete_row(bx, half_x0, half_x1)
        if not full:
            continue
        span = full[-1][0] + full[-1][2] - full[0][0]
        if span < 0.55 * (page_w / 2):
            continue
        good.append({'side': r['side'], 'top': min(b[1] for b in full), 'bottom': max(b[1] + b[3] for b in full),
                     'boxes': full, 'inferred': len(bx) == 4})
    questions = []
    for side in (0, 1):
        prev_bottom = 0
        for r in sorted([g for g in good if g['side'] == side], key=lambda g: g['top']):
            band = [b for b in boxes if side_of(b) == side and b[1] >= prev_bottom and b[1] + b[3] <= r['top'] - 2
                    and b not in r['boxes'] and b[2] >= 0.3 * DPI and b[3] >= 0.3 * DPI]
            if not band:
                prev_bottom = r['bottom']
                continue
            x0 = min(b[0] for b in band); y0 = min(b[1] for b in band)
            x1 = max(b[0] + b[2] for b in band); y1 = max(b[1] + b[3] for b in band)
            questions.append({'side': side, 'y': y0, 'matrix': (x0, y0, x1 - x0, y1 - y0), 'options': r['boxes'],
                              'parts': len(band), 'inferred': r['inferred']})
            prev_bottom = r['bottom']
    questions.sort(key=lambda q: (q['side'], q['y']))
    return questions


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
for ti, t in enumerate(cfg['tests']):
    answers = t.get('answers', '').split()
    expl = cfg.get('explanations', {}).get(str(ti + 1), {})
    tdir = os.path.join(out_root, f'test{ti + 1}')
    os.makedirs(tdir, exist_ok=True)
    qs = []
    n = 0
    first, last = t['pages']
    for page_no in range(first, last + 1):
        if page_no in cfg.get('skip_pages', []):
            continue
        img = render(page_no)
        boxes = find_boxes(img)
        found = group_questions(boxes, img.shape[1], img.shape[0])
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
            n += 1
            if dry:
                continue
            base = f'q{n:02d}'
            save(os.path.join(tdir, base + '_m.jpg'), crop(img, q['matrix'], 6))
            for li, b in enumerate(q['options']):
                save(os.path.join(tdir, f'{base}_{"abcde"[li]}.jpg'), crop(img, b, 5))
            ans = answers[n - 1] if n - 1 < len(answers) else None
            qs.append({'n': n, 'answer': ans, 'explanation': expl.get(str(n), ''), 'page': page_no})
            count += 1
            if limit and count >= limit:
                break
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
