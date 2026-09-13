"""Extract Gateway Gifted CogAT math workbooks (vector PDFs with a text layer).

Each question is a numbered row: a picture of the puzzle (gray equation box, arrow table
or bracket pairs) followed by a row of five numeric answer choices with radio circles.
The puzzle is cropped as an image; the choices become text options (big tappable numbers).

usage: python extract_cogat.py <pdf> <book_id> <config.json> [--limit N]
config: {"tests": [{"name": "...", "pages": [1, 4]}, ...], "answer_page": 8}
Answer key page lists one block of "n. X" per test, in test order.
"""
import sys, os, re, json
import pymupdf

pdf_path, book_id, cfg_path = sys.argv[1], sys.argv[2], sys.argv[3]
limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
cfg = json.load(open(cfg_path, encoding='utf-8'))
out_root = os.path.join(os.path.dirname(__file__), '..', 'docs', 'books', book_id)
SCALE = 3
doc = pymupdf.open(pdf_path)
NUM = re.compile(r'^-?\d+(\.\d+)?$')


def answer_blocks(page_no):
    """Split the answer key page into consecutive 1..n blocks."""
    text = doc[page_no - 1].get_text()
    items = re.findall(r'(\d{1,2})\.\s*([A-E])', text)
    blocks, cur = [], []
    for n, L in items:
        if int(n) == 1 and cur:
            blocks.append(cur); cur = []
        cur.append(L)
    if cur:
        blocks.append(cur)
    return blocks


def page_questions(page):
    """Yield {num, crop_rect, options} for every question row on a page."""
    words = page.get_text('words')
    W, H = page.rect.width, page.rect.height
    body = [w for w in words if 40 < w[1] < H - 40]
    # option rows: five numeric words sharing a baseline, spread across the page
    clusters = []          # numeric words grouped by baseline (within 8 pt)
    for w in sorted((w for w in body if NUM.match(w[4])), key=lambda w: w[3]):
        if clusters and abs(clusters[-1][-1][3] - w[3]) < 8:
            clusters[-1].append(w)
        else:
            clusters.append([w])
    opt_rows = []
    for ws in clusters:
        ws = sorted(ws, key=lambda w: w[0])
        if len(ws) >= 5:
            # keep the five that follow radio circles (x spacing ~ regular, spanning > 200pt)
            cand = ws[-5:] if len(ws) > 5 else ws
            if cand[-1][0] - cand[0][0] > 200:
                opt_rows.append(cand)
    # question numbers: a numeric word in the left margin, above an option row
    qnums = [w for w in body if NUM.match(w[4]) and w[0] < 60 and w[2] - w[0] < 30]
    drawings = [d['rect'] for d in page.get_drawings() if d['rect'].width > 30 and d['rect'].x0 > 60]
    images = [pymupdf.Rect(i['bbox']) for i in page.get_image_info()]
    prev_bottom = 40
    out = []
    for opts in opt_rows:
        top = min(w[1] for w in opts)
        band_nums = [w for w in qnums if prev_bottom <= w[1] < top]
        num = int(band_nums[0][4]) if band_nums else None
        # picture: drawings (gray boxes/arrows/brackets) and text between prev row and this row,
        # right of the number column, not inside a mascot image
        parts = [r for r in drawings if r.y0 >= prev_bottom - 2 and r.y1 <= top - 2]
        token = lambda t: NUM.match(t) or t in ('+', '-', 'x', 'X', '/', '=', '?', '[', ']') or re.fullmatch(r'\[?-?\d+(\.\d+)?\]?', t)
        parts += [pymupdf.Rect(w[:4]) for w in body if w[1] >= prev_bottom and w[3] <= top - 2 and w[0] > 60
                  and token(w[4]) and not any(pymupdf.Rect(w[:4]).intersects(im) for im in images)
                  and not (w in qnums)]
        parts = [r for r in parts if not any(r.intersects(im) and im.width > 60 for im in images)]
        if not parts:
            prev_bottom = max(w[3] for w in opts) + 2
            continue
        rect = parts[0]
        for r in parts[1:]:
            rect |= r
        rect = rect + (-8, -8, 8, 8)
        out.append({'num': num, 'rect': rect, 'options': [w[4] for w in opts]})
        prev_bottom = max(w[3] for w in opts) + 2
    return out


book = {'id': book_id, 'ext': 'png', 'tests': []}
blocks = answer_blocks(cfg['answer_page'])
count = 0
for ti, t in enumerate(cfg['tests']):
    answers = blocks[ti] if ti < len(blocks) else []
    tdir = os.path.join(out_root, f'test{ti + 1}')
    os.makedirs(tdir, exist_ok=True)
    qs = []
    n = 0
    for page_no in range(t['pages'][0], t['pages'][1] + 1):
        page = doc[page_no - 1]
        for q in page_questions(page):
            n += 1
            if q['num'] not in (None, n):
                print(f'  warning: page {page_no} question numbered {q["num"]} but counted {n}')
            pix = page.get_pixmap(matrix=pymupdf.Matrix(SCALE, SCALE), clip=q['rect'], alpha=False)
            pix.save(os.path.join(tdir, f'q{n:02d}_m.png'))
            qs.append({'n': n, 'answer': answers[n - 1] if n - 1 < len(answers) else None,
                       'explanation': '', 'page': page_no, 'options': q['options']})
            count += 1
            if limit and count >= limit:
                break
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
