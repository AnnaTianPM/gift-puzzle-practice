"""Extract NNAT questions (matrix image + 5 option images) and answer keys from an
Origins Publications practice-test PDF into a static site data folder.

usage: python extract.py <pdf> <book_id> [--limit N]
"""
import sys, re, json, os
import pymupdf

pdf_path, book_id = sys.argv[1], sys.argv[2]
limit = int(sys.argv[sys.argv.index('--limit')+1]) if '--limit' in sys.argv else None
out_root = os.path.join(os.path.dirname(__file__), '..', 'docs', 'books', book_id)
SCALE = 3  # 216 dpi
LETTERS = ['Ⓐ','Ⓑ','Ⓒ','Ⓓ','Ⓔ']

doc = pymupdf.open(pdf_path)

def find_tests(doc):
    """Return list of (name, first_page_idx, last_page_idx) for practice tests."""
    tests = []
    for i, p in enumerate(doc):
        t = p.get_text()
        m = re.search(r'Practice Test (One|Two|Three|Four)\s*\n', t)
        if m and 'bubble sheets can be found' in t:
            tests.append([m.group(1), i+1, None])
        if tests and ('Bubble Sheets' in t and '& Answers' in t) and tests[-1][2] is None:
            tests[-1][2] = i-1
    for k in range(len(tests)-1):
        if tests[k][2] is None: tests[k][2] = tests[k+1][1]-2
    return tests

def find_answers(doc):
    """Return {test_name: {num: (letter, explanation)}} parsed from answer pages."""
    text = ''
    for p in doc:
        t = p.get_text()
        if 'Answer Explanations' in t or re.search(r'^\d{1,2}\.\s+[A-E]\.', t, re.M):
            text += '\n' + t
    # split by test headings like 'NNAT C Test One'
    # headings look like 'NNAT C Test One' or just 'Test Two.' (never 'Test Prep')
    parts = re.split(r'\bTest (One|Two|Three|Four)\b\.?', text)
    result = {}
    for k in range(1, len(parts), 2):
        name, body = parts[k], parts[k+1]
        body = re.sub(r'\n', ' ', body)
        body = re.sub(r'\s+', ' ', body)
        # strip running headers/footers
        # Running headers/footers differ slightly between books (Level C/D: 'Origins Publications',
        # 'NNAT® Level C Test Prep Workbook'; Level B: 'Origins Tutoring', 'NNAT® B Test Prep Workbook').
        body = re.sub(r'(\d{1,3}\s*)?NNAT® (Level )?[A-D]\s+Test Prep Workbook(\s*\d{1,3}(?=\s))?', ' ', body)
        body = re.sub(r'(\d{1,3}\s*)?Origins (Publications|Tutoring), Inc(\s*\d{1,3}(?=\s))?', ' ', body)
        body = re.sub(r'NNAT® (Level )?[A-D]\s+(Practice Test Answers|Answer Explanations|Answers and Explanations|Practice Test)', ' ', body)
        body = re.sub(r'\s+', ' ', body)
        items = re.findall(r'(?<!\d)(\d{1,2})\.\s?([A-E])\.\s(.*?)(?=(?<!\d)\d{1,2}\.\s?[A-E]\.\s|$)', body)
        d = result.setdefault(name, {})
        for num, letter, expl in items:
            n = int(num)
            expl = re.sub(r'\s*NNAT\S*(\s+[A-D])?\s*$', '', expl.strip())
            if n not in d:
                d[n] = (letter, expl)
    return result

def clip_png(page, rect, path):
    pix = page.get_pixmap(matrix=pymupdf.Matrix(SCALE, SCALE), clip=rect, alpha=False)
    pix.save(path)

def union(rects):
    r = pymupdf.Rect(rects[0])
    for x in rects[1:]: r |= x
    return r

def extract_page(page, page_no):
    """Yield dicts {num, matrix_rect, option_rects}."""
    words = page.get_text('words')
    labels = [w for w in words if w[4] in LETTERS]
    # cluster label rows by y0
    rows = {}
    for w in labels:
        key = round(w[1]/10)
        rows.setdefault(key, []).append(w)
    rows = [sorted(v, key=lambda w: w[0]) for k, v in sorted(rows.items())]
    rows = [r for r in rows if len(r) == 5]
    nums = [w for w in words if re.fullmatch(r'\d{1,2}', w[4]) and w[0] < 100 and 70 < w[1] < 750]
    all_drawings = [d['rect'] for d in page.get_drawings()]
    visible = [d['rect'] for d in page.get_drawings() if not (d.get('fill') == (1.0, 1.0, 1.0) and d.get('color') is None)]
    frame_items = [pymupdf.Rect(it[1]) for d in page.get_drawings() for it in d['items'] if it[0] == 're']
    frame_items = [f for f in frame_items if 24 <= f.width <= 70 and 24 <= f.height <= 60]
    # drop horizontal rules and the page frame
    drawings = [r for r in all_drawings if not (r.height < 2 and r.width > 300) and r.width < 560 and not (r.width < 3 and r.height < 3)]
    prev_bottom = 70
    for row in rows:
        ly0 = min(w[1] for w in row); ly1 = max(w[3] for w in row)
        # Option boxes sit just above their letters and are centred on them. Measure the
        # box size from frame-like drawings in this row (some rows draw all five frames as
        # one wide path; inner shapes alone would give a crop that is too tight), then use
        # one uniform box per option so stray marks near a box never distort the crop.
        centers = [(w[0]+w[2])/2 for w in row]
        band = lambda r: r.y1 <= ly0+1 and r.y0 >= ly0-50   # boxes are <=45pt tall, just above the letters
        frames = []
        for cx in centers:
            cand = [r for r in drawings if band(r) and r.x0 >= cx-55 and r.x1 <= cx+55 and r.width < 80]
            if cand:
                u = union(cand)
                if 24 <= u.height <= 45 and 24 <= u.width <= 70 and ly0 - u.y1 <= 15:
                    frames.append(u)
        wide = [r for r in all_drawings if band(r) and r.width > 300 and 20 <= r.height <= 60]
        if frames:
            big = max(frames, key=lambda r: r.width * r.height)
            W, y0, y1 = big.width, big.y0, big.y1
        elif wide:
            W, y0, y1 = 2*(centers[0]-wide[0].x0), wide[0].y0, wide[0].y1
            print(f'  note: page {page_no} row y={ly0:.0f}: box size from wide frame path')
        else:
            W, y0, y1 = 42, ly0-40, ly0-6
            print(f'  note: page {page_no} row y={ly0:.0f}: default box size')
        opt_rects = []
        frame_tops = []
        for cx in centers:
            # Prefer the exact frame rectangle drawn for this option (frames are often
            # emitted as 're' items of one shared path), matched by nearest centre.
            near = [f for f in frame_items if f.y1 >= ly0-15 and f.y1 <= ly0+3 and abs((f.x0+f.x1)/2 - cx) <= 30]
            if near:
                f = max(near, key=lambda f: f.width * f.height)   # outer frame, not an inner shape
                frame_tops.append(f.y0)
                # Occasionally the book draws an option's small shapes touching the top edge of its
                # frame (a layout slip in the book); keep them so the option is not shown empty.
                above = [r for r in visible if r.x0 >= f.x0-2 and r.x1 <= f.x1+2 and f.y0-3 <= r.y1 <= f.y0+2
                         and r.y0 >= f.y0-30 and r.height <= 25]
                for r in above:
                    f = f | r
                    print(f'  note: page {page_no} option {row[len(opt_rects)][4]} has shapes above its frame; included')
                opt_rects.append(f + (-4, -4, 4, 4))
            else:
                frame_tops.append(y0)
                opt_rects.append(pymupdf.Rect(cx-W/2, y0, cx+W/2, y1) + (-4, -4, 4, 4))
        opt_top = min(frame_tops) - 4
        # matrix: drawings between prev_bottom and opt_top
        cand = [r for r in drawings if r.y0 >= prev_bottom and r.y1 <= opt_top-2 and r.x0 > 85]
        if not cand:
            raise RuntimeError(f'no matrix drawing on page {page_no} row at y={ly0}')
        mrect = union(cand) + (-4, -4, 4, 4)
        rules = [r.y0 for r in all_drawings if r.height < 2 and r.width > 300 and prev_bottom - 20 <= r.y0 <= mrect.y0 + 10]
        if rules:
            mrect.y0 = max(mrect.y0, max(rules) + 1.5)
        if os.environ.get('DEBUG_PAGE') == str(page_no):
            print(f'  debug p{page_no} row ly0={ly0:.0f} opt_top={opt_top:.1f} frames={len(frames)} matrix={[round(v) for v in mrect]}')
        # question number in this band
        qn = [w for w in nums if prev_bottom <= w[1] <= ly1]
        num = int(qn[0][4]) if qn else None
        yield dict(num=num, matrix=mrect, options=opt_rects)
        prev_bottom = ly1 + 2

tests = find_tests(doc)
answers = find_answers(doc)
print('tests:', tests)
print('answers found:', {k: len(v) for k, v in answers.items()})

book = {'id': book_id, 'tests': []}
count = 0
for name, first, last in tests:
    tdir = os.path.join(out_root, f'test{len(book["tests"])+1}')
    os.makedirs(tdir, exist_ok=True)
    qs = []
    for pi in range(first, last+1):
        page = doc[pi]
        for q in extract_page(page, pi+1):
            n = q['num']
            base = f'q{n:02d}'
            clip_png(page, q['matrix'], os.path.join(tdir, base + '_m.png'))
            for li, r in enumerate(q['options']):
                clip_png(page, r, os.path.join(tdir, f'{base}_{"abcde"[li]}.png'))
            ans = answers.get(name, {}).get(n, (None, ''))
            qs.append({'n': n, 'answer': ans[0], 'explanation': ans[1], 'page': pi+1})
            count += 1
            if limit and count >= limit: break
        if limit and count >= limit: break
    qs.sort(key=lambda q: q['n'])
    book['tests'].append({'name': f'Practice Test {name}', 'dir': os.path.basename(tdir), 'questions': qs})
    if limit and count >= limit: break

with open(os.path.join(out_root, 'book.json'), 'w', encoding='utf-8') as f:
    json.dump(book, f, ensure_ascii=False, indent=1)
print('wrote', count, 'questions to', out_root)

# also emit a script version so the site loads without fetch()
with open(os.path.join(out_root, 'book.js'), 'w', encoding='utf-8') as f:
    f.write('window.NNAT_BOOKS = window.NNAT_BOOKS || {};\nwindow.NNAT_BOOKS[' + json.dumps(book_id) + '] = ' + json.dumps(book, ensure_ascii=False) + ';\n')
