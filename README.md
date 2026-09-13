# Puzzle Practice (NNAT quiz site)

Static website that turns NNAT practice-test PDFs into a click-to-answer quiz for kids.

- `site/` — the website. Upload this folder as-is to GitHub Pages (or any static host).
- `tools/extract.py` — builds `site/books/<book-id>/` from a PDF (question images + answers).
- `tools/montage.py` — builds review sheets so every crop can be checked by eye.

## Add a book

```bash
pip install pymupdf
python tools/extract.py "path/to/book.pdf" my-book-id
```

Then add one line to `site/books/index.js` with the book id and a title.

## Preview locally

```bash
python -m http.server 8765 --directory site
```

Open http://localhost:8765
