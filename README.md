# Puzzle Practice (NNAT quiz site)

Static website that turns NNAT practice-test PDFs into a click-to-answer quiz for kids.

- `docs/` — the website. GitHub Pages serves this folder (Settings → Pages → main branch, /docs folder) (or any static host).
- `tools/extract.py` — builds `docs/books/<book-id>/` from a PDF (question images + answers).
- `tools/montage.py` — builds review sheets so every crop can be checked by eye.

## Add a book

```bash
pip install pymupdf
python tools/extract.py "path/to/book.pdf" my-book-id
```

Then add one line to `docs/books/index.js` with the book id and a title.

## Preview locally

```bash
python -m http.server 8765 --directory docs
```

Open http://localhost:8765
