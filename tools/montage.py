"""Build review montages: N questions per PNG, each cell = matrix + 5 options, answer marked."""
import sys, os, json, pymupdf
book_dir, out_dir = sys.argv[1], sys.argv[2]
PER = 8; COLS = 2; CW, CH = 300, 230
book = json.load(open(os.path.join(book_dir, 'book.json'), encoding='utf-8'))
os.makedirs(out_dir, exist_ok=True)
for t in book['tests']:
    qs = t['questions']
    for s in range(0, len(qs), PER):
        chunk = qs[s:s+PER]
        rows = (len(chunk)+COLS-1)//COLS
        doc = pymupdf.open(); page = doc.new_page(width=CW*COLS, height=CH*rows)
        for i, q in enumerate(chunk):
            x0 = (i % COLS)*CW; y0 = (i // COLS)*CH
            base = os.path.join(book_dir, t['dir'], f"q{q['n']:02d}")
            page.draw_rect(pymupdf.Rect(x0, y0, x0+CW, y0+CH), color=(0.7,0.7,0.7))
            page.insert_text((x0+6, y0+16), f"Q{q['n']}  ans {q['answer']}  p{q['page']}", fontsize=11)
            page.insert_image(pymupdf.Rect(x0+10, y0+20, x0+CW-10, y0+150), filename=base+'_m.png', keep_proportion=True)
            for k, L in enumerate('abcde'):
                ox = x0+8+k*57
                r = pymupdf.Rect(ox, y0+158, ox+52, y0+210)
                page.insert_image(r, filename=f'{base}_{L}.png', keep_proportion=True)
                lab = L.upper()
                if lab == q['answer']:
                    page.draw_rect(r, color=(0,0.6,0), width=2)
                page.insert_text((ox+20, y0+224), lab, fontsize=10)
        name = f"{t['dir']}_q{chunk[0]['n']:02d}-{chunk[-1]['n']:02d}.png"
        page.get_pixmap(dpi=110).save(os.path.join(out_dir, name))
        print(name)
