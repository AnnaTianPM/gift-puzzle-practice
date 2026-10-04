/* Puzzle Practice - static quiz app for NNAT-style picture puzzles. No build step.
 *
 * A "session" is one run through a list of puzzles. Three kinds:
 *   test      one practice test of a book, in order (progress is saved per test)
 *   free      N random puzzles drawn from every test of a book (new draw each time)
 *   mistakes  every puzzle answered wrong so far, from any book (right answers remove it)
 * Everything is kept in localStorage, so a child can close the browser and carry on later.
 */
(function () {
  const LETTERS = ['A', 'B', 'C', 'D', 'E'];
  const app = document.getElementById('app');
  const books = window.NNAT_BOOK_LIST || [];
  const bookById = {};
  books.forEach(b => { bookById[b.id] = b; });
  const state = { book: null, session: null, timerHandle: null, freeCount: 10, mode: 'practice', timerOn: true, showFixed: false };
  const EXAM_SECONDS = 30 * 60;

  // ---------- storage ----------
  function lsGet(k) { try { const r = localStorage.getItem(k); return r ? JSON.parse(r) : null; } catch (e) { return null; } }
  function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ } }
  function lsDel(k) { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } }
  const testKey = (bookId, dir) => 'nnat:s:' + bookId + ':' + dir;
  const freeKey = bookId => 'nnat:s:free:' + bookId;
  const MISTAKES_SESSION = 'nnat:s:mistakes';
  const MISTAKES = 'nnat:mistakes';

  function getMistakes() { return lsGet(MISTAKES) || {}; }
  const isFixed = e => !!e.fixed;                    // last attempt was right
  const wrongPicks = e => (e.tries || []).filter(t => !t.ok && t.p).map(t => t.p);

  // Every answer to a puzzle that has ever been wrong is appended here. Nothing is ever
  // deleted: getting it right only flips `fixed`, so the record stays readable later.
  function noteResult(item, right, pick) {
    const m = getMistakes();
    const e = m[item.key];
    if (!e && right) return;                         // first time right: never was a mistake
    const rec = e || { bookId: item.bookId, testDir: item.testDir, n: item.n, count: 0, tries: [] };
    rec.tries = (rec.tries || []).concat([{ p: pick || null, ok: !!right, at: Date.now() }]);
    if (rec.tries.length > 20) rec.tries = rec.tries.slice(-20);
    rec.fixed = !!right;
    rec.at = Date.now();
    if (!right) { rec.pick = pick || null; rec.count = (rec.count || 0) + 1; }
    m[item.key] = rec;
    lsSet(MISTAKES, m);
  }

  // Older versions did not record which option was picked. Recover it from the saved
  // sessions, which still hold every answer. Runs on load; only fills blanks, never
  // removes a mistake. A one-time copy of the list is kept in case this goes wrong.
  function migrateMistakes() {
    const m = getMistakes();
    if (!Object.keys(m).length) return;
    if (!lsGet(MISTAKES + '.bak1')) lsSet(MISTAKES + '.bak1', { at: Date.now(), mistakes: m });
    const best = {};           // key -> { pick, at } from the most recent session that got it wrong
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k || k.indexOf('nnat:s:') !== 0) continue;
      const sess = lsGet(k);
      if (!sess || !sess.items || !sess.answers) continue;
      sess.items.forEach(it => {
        const a = sess.answers[it.key];
        if (!a || a === it.answer) return;
        if (!best[it.key] || (sess.at || 0) > best[it.key].at) best[it.key] = { pick: a, at: sess.at || 0 };
      });
    }
    let changed = false;
    Object.keys(m).forEach(key => {
      const e = m[key];
      if (!e.pick && best[key]) { e.pick = best[key].pick; changed = true; }
      if (!e.tries) {                                // records from before attempts were kept
        e.tries = e.pick ? [{ p: e.pick, ok: false, at: e.at || Date.now() }] : [];
        changed = true;
      }
      if (e.fixed === undefined) { e.fixed = false; changed = true; }
    });
    if (changed) lsSet(MISTAKES, m);
  }

  // test name as the book lists it ("Language 1"), not the folder name ("test4")
  function testNameOf(bookId, testDir) {
    const b = bookById[bookId];
    const i = parseInt(String(testDir).replace('test', ''), 10) - 1;
    return (b && b.tests && b.tests[i]) || testDir;
  }
  function mistakeStub(e) {
    return { bookId: e.bookId, testDir: e.testDir, n: e.n, ext: (bookById[e.bookId] || {}).ext || 'png' };
  }

  // ---------- data loading ----------
  const loaded = {};
  function loadBook(id) {
    if (loaded[id]) return Promise.resolve(loaded[id]);
    return new Promise((resolve, reject) => {
      const done = () => { loaded[id] = Object.assign({}, bookById[id] || {}, window.NNAT_BOOKS[id]); resolve(loaded[id]); };
      if (window.NNAT_BOOKS && window.NNAT_BOOKS[id]) return done();
      const s = document.createElement('script');
      s.src = 'books/' + id + '/book.js?v=' + Date.now();
      s.onload = done;
      s.onerror = () => reject(new Error('Could not load book ' + id));
      document.head.appendChild(s);
    });
  }
  function makeItem(book, test, q) {
    return {
      key: book.id + '/' + test.dir + '/' + q.n, bookId: book.id, testDir: test.dir, testName: test.name,
      ext: book.ext || 'png', prompt: test.prompt || '', n: q.n, answer: q.answer, explanation: q.explanation || '',
      options: q.options || null, nopts: q.nopts || 5, stem: q.stem !== false,
      note: (window.NNAT_NOTES || {})[book.id + '/' + test.dir + '/' + q.n] || null,
    };
  }
  function imgPath(item, suffix) {
    return 'books/' + item.bookId + '/' + item.testDir + '/q' + String(item.n).padStart(2, '0') + '_' + suffix + '.' + item.ext;
  }

  // ---------- sessions ----------
  function newSession(kind, key, title, items, mode, timerOn) {
    return { kind, key, title, items, mode, timerOn: !!timerOn, idx: 0, answers: {}, revealed: {}, finished: false, timeLeft: null, at: Date.now() };
  }
  function save() { if (state.session && !state.session.transient) lsSet(state.session.key, state.session); }
  function items() { return state.session.items; }
  function answered(s) { return s.items.filter(it => s.answers[it.key]).length; }
  function firstOpen(s) {
    // index of the first puzzle that still needs work
    const i = s.items.findIndex(it => !s.answers[it.key] || (s.mode === 'practice' && !s.revealed[it.key]));
    return i < 0 ? Math.min(s.idx || 0, s.items.length - 1) : i;
  }
  function scoreInfo(s) {
    let ok = 0, done = 0;
    s.items.forEach(it => { const a = s.answers[it.key]; if (a) { done++; if (a === it.answer) ok++; } });
    return { ok, done, total: s.items.length };
  }
  function pickRandom(arr, n) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
    return a.slice(0, n);
  }

  // ---------- helpers ----------
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const k in attrs || {}) {
      if (k === 'class') el.className = attrs[k];
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), attrs[k]);
      else if (k === 'html') el.innerHTML = attrs[k];
      else el.setAttribute(k, attrs[k]);
    }
    for (const c of children.flat(Infinity)) if (c != null) el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    return el;
  }
  function render(...nodes) { app.replaceChildren(...nodes); window.scrollTo(0, 0); }
  function fmtTime(s) { const m = Math.floor(s / 60), r = s % 60; return m + ':' + String(r).padStart(2, '0'); }
  function topBar(title, left, right) {
    return h('div', { class: 'bar' }, left || h('div', { class: 'spacer' }), h('div', { class: 'title' }, title), right || h('div', { class: 'spacer' }));
  }
  function backBtn(fn) { return h('button', { class: 'icon-btn', onclick: fn, title: 'Back' }, '←'); }
  function bar(done, total, cls) {
    return h('div', { class: 'mini-progress' }, h('div', { class: cls || '', style: 'width:' + Math.round(100 * done / Math.max(1, total)) + '%' }));
  }
  function tagChip(b) { return b.tag ? h('span', { class: 'tag ' + (b.tagClass || '') }, b.tag) : null; }

  // ---------- timer ----------
  function stopTimer() { if (state.timerHandle) { clearInterval(state.timerHandle); state.timerHandle = null; } }
  function startTimer() {
    stopTimer();
    const s = state.session;
    if (!(s.mode === 'exam' && s.timerOn) || s.finished) return;
    if (s.timeLeft == null) s.timeLeft = EXAM_SECONDS;
    state.timerHandle = setInterval(() => {
      s.timeLeft--;
      const el = document.getElementById('timer');
      if (el) { el.textContent = fmtTime(s.timeLeft); el.classList.toggle('low', s.timeLeft <= 60); }
      if (s.timeLeft % 5 === 0) save();
      if (s.timeLeft <= 0) finish();
    }, 1000);
  }

  // ---------- home ----------
  function viewHome() {
    stopTimer(); state.session = null; state.book = null;
    const mistakes = getMistakes(); const nMist = Object.values(mistakes).filter(e => !isFixed(e)).length;
    const groups = [];
    books.forEach(b => {
      let g = groups.find(x => x.name === (b.group || 'Other'));
      if (!g) { g = { name: b.group || 'Other', items: [] }; groups.push(g); }
      g.items.push(b);
    });
    render(
      topBar('Puzzle Practice'),
      h('div', { class: 'page' },
        h('button', { class: 'big-btn mist' + (nMist ? '' : ' empty'), onclick: viewMistakes },
          h('span', { class: 'emoji' }, '📕'),
          h('span', {}, h('div', { class: 'label' }, 'My Mistakes'),
            h('div', { class: 'sub' }, nMist ? nMist + (nMist > 1 ? ' puzzles' : ' puzzle') + ' to fix · tap to practice' : 'No mistakes yet. Wrong answers collect here.'))),
        groups.map(g => [
          h('h2', { class: 'group-title' }, g.name),
          g.items.map(b => {
            // progress summary from saved test sessions (no need to load the book)
            const lines = [];
            (b.tests || []).forEach((tn, i) => {
              const s = lsGet(testKey(b.id, 'test' + (i + 1)));
              if (!s) return;
              const sc = scoreInfo(s);
              if (s.finished) lines.push(tn + ': ' + sc.ok + '/' + sc.total + ' ✓');
              else if (sc.done) lines.push(tn + ': at puzzle ' + (firstOpen(s) + 1) + ' of ' + sc.total);
            });
            return h('button', { class: 'big-btn', onclick: () => openBook(b) },
              h('span', { class: 'emoji' }, b.emoji || '📘'),
              h('span', { class: 'grow' },
                h('div', { class: 'label' }, b.title, ' ', tagChip(b)),
                h('div', { class: 'sub' }, b.subtitle || ''),
                lines.length ? h('div', { class: 'sub cont' }, '▶ ' + lines.join(' · ')) : null));
          }),
        ])
      )
    );
  }

  function openBook(b, then) {
    render(topBar(b.title, backBtn(viewHome)), h('div', { class: 'page center muted' }, 'Loading…'));
    loadBook(b.id).then(data => { state.book = data; (then || viewBook)(); })
      .catch(err => render(topBar(b.title, backBtn(viewHome)), h('div', { class: 'page center' }, err.message)));
  }

  // ---------- book: tests + free practice ----------
  function viewBook() {
    const b = state.book;
    const total = b.tests.reduce((n, t) => n + t.questions.length, 0);
    const counts = [10, 20, 30].filter(n => n < total).concat([total]);
    if (!counts.includes(state.freeCount)) state.freeCount = counts[0];
    const freeSaved = lsGet(freeKey(b.id));
    render(
      topBar(b.title, backBtn(viewHome)),
      h('div', { class: 'page' },
        h('h1', { class: 'center' }, 'Pick a test'),
        b.tests.map((t, i) => {
          const s = lsGet(testKey(b.id, t.dir));
          const sc = s ? scoreInfo(s) : { ok: 0, done: 0, total: t.questions.length };
          let sub, extra = null;
          if (s && s.finished) { sub = 'Finished · score ' + sc.ok + ' / ' + sc.total; extra = bar(sc.ok, sc.total, 'ok'); }
          else if (s && sc.done) { sub = sc.done + ' of ' + sc.total + ' done · continue at puzzle ' + (firstOpen(s) + 1); extra = bar(sc.done, sc.total); }
          else sub = t.questions.length + ' puzzles';
          return h('button', { class: 'big-btn', onclick: () => viewSetup('test', t) },
            h('span', { class: 'emoji' }, ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣'][i] || '📝'),
            h('span', { class: 'grow' }, h('div', { class: 'label' }, t.name), h('div', { class: 'sub' }, sub), extra));
        }),
        h('div', { class: 'card free' },
          h('h2', {}, '🎲 Free Practice'),
          h('div', { class: 'muted' }, 'Random puzzles from all ' + b.tests.length + ' tests. New ones every time.'),
          h('div', { class: 'small-label' }, 'How many?'),
          h('div', { class: 'row' }, counts.map(n => h('button', { class: 'chip' + (state.freeCount === n ? ' on' : ''), onclick: () => { state.freeCount = n; viewBook(); } }, n === total ? 'All ' + total : String(n)))),
          freeSaved && !freeSaved.finished && answered(freeSaved)
            ? h('div', { class: 'resume', style: 'margin-top:12px' },
              h('div', {}, h('b', {}, 'Unfinished free practice: '), answered(freeSaved) + ' of ' + freeSaved.items.length + ' done.'),
              h('div', { class: 'row', style: 'margin-top:8px' },
                h('button', { class: 'primary', onclick: () => resumeSession(freeSaved) }, 'Continue'),
                h('button', { class: 'secondary', onclick: () => { lsDel(freeKey(b.id)); viewBook(); } }, 'Discard')))
            : null,
          h('div', { class: 'center', style: 'margin-top:14px' }, h('button', { class: 'primary wide', onclick: () => viewSetup('free', null) }, 'Start ▶')))
      )
    );
  }

  // ---------- setup: choose mode, resume ----------
  function viewSetup(kind, test) {
    const b = state.book;
    const key = kind === 'test' ? testKey(b.id, test.dir) : freeKey(b.id);
    const saved = kind === 'test' ? lsGet(key) : null;
    const title = kind === 'test' ? test.name : 'Free Practice · ' + state.freeCount + ' puzzles';
    const modeCard = (mode, t, desc) => h('div', { class: 'choice' + (state.mode === mode ? ' on' : ''), onclick: () => { state.mode = mode; viewSetup(kind, test); } },
      h('b', {}, t), h('span', { class: 'muted' }, desc));
    const resume = saved && answered(saved) && !saved.finished
      ? h('div', { class: 'resume' },
        h('div', {}, h('b', {}, 'Continue where you left off?'), ' ', answered(saved) + ' of ' + saved.items.length + ' done. Next up: puzzle ' + (firstOpen(saved) + 1) + '.'),
        h('div', { class: 'row', style: 'margin-top:10px' },
          h('button', { class: 'primary', onclick: () => resumeSession(saved) }, 'Continue ▶'),
          h('button', { class: 'secondary', onclick: () => { lsDel(key); viewSetup(kind, test); } }, 'Start over')))
      : null;
    const review = saved && saved.finished
      ? h('div', { class: 'resume' }, h('div', {}, h('b', {}, 'Finished last time: ' + scoreInfo(saved).ok + ' / ' + saved.items.length + '.'), ' You can review the answers or start again.'),
        h('div', { class: 'row', style: 'margin-top:10px' },
          h('button', { class: 'secondary', onclick: () => { state.session = saved; viewResults(); } }, 'Review answers'),
          h('button', { class: 'secondary', onclick: () => { lsDel(key); viewSetup(kind, test); } }, 'Clear result')))
      : null;
    render(
      topBar(title, backBtn(viewBook)),
      h('div', { class: 'page' },
        resume, review,
        h('div', { class: 'card' },
          h('h2', {}, 'How do you want to play?'),
          h('div', { class: 'choice-grid' },
            modeCard('practice', '🎯 Practice', 'See if you are right after each puzzle, with a hint.'),
            modeCard('exam', '⏱️ Test', 'Answer all puzzles first, then see your score.')),
          state.mode === 'exam' && kind === 'test' ? h('label', { class: 'check' },
            h('input', { type: 'checkbox', ...(state.timerOn ? { checked: '' } : {}), onchange: e => { state.timerOn = e.target.checked; } }),
            h('span', {}, '30 minute timer')) : null),
        h('div', { class: 'center' }, h('button', { class: 'primary', onclick: () => startSession(kind, test) }, resume ? 'Start a new one ▶' : 'Start ▶'))
      )
    );
  }

  function startSession(kind, test) {
    const b = state.book;
    let its, key, title;
    if (kind === 'test') {
      its = test.questions.map(q => makeItem(b, test, q)); key = testKey(b.id, test.dir); title = test.name;
    } else {
      const all = [];
      b.tests.forEach(t => t.questions.forEach(q => all.push(makeItem(b, t, q))));
      its = pickRandom(all, state.freeCount); key = freeKey(b.id); title = 'Free Practice';
    }
    state.session = newSession(kind, key, title, its, state.mode, kind === 'test' && state.timerOn);
    save(); startTimer(); viewQuestion();
  }
  function resumeSession(s) {
    state.session = s;
    if (s.finished) { viewResults(); return; }
    s.idx = firstOpen(s); save(); startTimer(); viewQuestion();
  }

  // ---------- mistakes ----------
  const keyOfRec = e => e.bookId + '/' + e.testDir + '/' + e.n;
  function mistakeCard(e, onTap) {
    const stub = mistakeStub(e);
    const had = wrongPicks(e);
    const fixed = isFixed(e);
    return h('button', { class: 'mist-card' + (fixed ? ' done' : ''), onclick: onTap },
      h('div', { class: 'thumb-wrap' },
        h('img', { class: 'thumb', src: imgPath(stub, 'm'), alt: '',
          onerror: ev => { const t = ev.target; if (!t.dataset.alt) { t.dataset.alt = '1'; t.src = imgPath(stub, 'a'); } } })),
      h('div', { class: 'mist-meta' },
        h('div', { class: 'mist-where' }, testNameOf(e.bookId, e.testDir) + ' #' + e.n),
        fixed
          ? h('div', { class: 'mist-ok' }, 'Got it right ✓')
          : h('div', { class: 'mist-pick' }, e.pick ? 'You picked ' + e.pick : 'Try again'),
        had.length > (fixed ? 0 : 1)
          ? h('div', { class: 'mist-count' }, (fixed ? 'had picked ' : 'tried ') + had.join(', ')) : null,
        (window.NNAT_NOTES || {})[keyOfRec(e)] ? h('div', { class: 'mist-note' }, '🤔 see note') : null));
  }

  function viewMistakes() {
    stopTimer(); state.session = null;
    const m = getMistakes();
    const todo = Object.values(m).filter(e => !isFixed(e));
    const done = Object.values(m).filter(isFixed);
    const saved = lsGet(MISTAKES_SESSION);
    const byOrder = (a, c) => a.testDir.localeCompare(c.testDir) || a.n - c.n;
    const group = list => {
      const per = {};
      list.forEach(e => { (per[e.bookId] = per[e.bookId] || []).push(e); });
      return per;
    };
    const perBook = group(todo);
    const perDone = group(done);
    const keyOf = e => e.bookId + '/' + e.testDir + '/' + e.n;
    render(
      topBar('My Mistakes', backBtn(viewHome)),
      h('div', { class: 'page' },
        h('h1', { class: 'center' }, todo.length ? todo.length + (todo.length > 1 ? ' puzzles' : ' puzzle') + ' to fix'
          : (done.length ? 'All fixed 🎉' : 'No mistakes yet')),
        h('p', { class: 'center muted' }, todo.length ? 'Tap a puzzle to look at it. Nothing is ever deleted.'
          : (done.length ? 'Everything you got wrong has been fixed. They are all kept below.'
            : 'Puzzles you get wrong will show up here so you can try them again.')),
        todo.length ? h('div', { class: 'row', style: 'justify-content:center;margin-bottom:16px' },
          h('button', { class: 'secondary', onclick: () => startReview(null, null, 'todo') }, '👀 Look through'),
          saved && !saved.finished && answered(saved)
            ? h('button', { class: 'primary', onclick: () => resumeSession(saved) }, 'Continue (' + answered(saved) + '/' + saved.items.length + ') ▶')
            : h('button', { class: 'primary', onclick: () => startMistakes(null) }, 'Try them again ▶'),
          saved && !saved.finished && answered(saved)
            ? h('button', { class: 'secondary', onclick: () => startMistakes(null) }, 'Start fresh') : null) : null,
        Object.keys(perBook).map(bid => {
          const b = bookById[bid] || { title: bid };
          const list = perBook[bid].slice().sort(byOrder);
          return h('div', { class: 'card' },
            h('div', { class: 'row between' },
              h('div', {}, h('b', {}, b.title), ' ', tagChip(b), h('div', { class: 'muted' }, list.length + ' puzzle' + (list.length > 1 ? 's' : ''))),
              h('button', { class: 'secondary', onclick: () => startMistakes(bid) }, 'Try again ▶')),
            h('div', { class: 'mist-grid' }, list.map(e => mistakeCard(e, () => startReview(bid, keyOf(e), 'todo')))));
        }),
        done.length ? h('div', { class: 'card done-box' },
          h('div', { class: 'row between' },
            h('div', {}, h('b', {}, '✓ Fixed'), h('div', { class: 'muted' }, done.length + ' puzzle' + (done.length > 1 ? 's' : '') + ' you got right later')),
            h('div', { class: 'row' },
              state.showFixed ? h('button', { class: 'secondary', onclick: () => startReview(null, null, 'fixed') }, '👀 Look through') : null,
              h('button', { class: 'secondary', onclick: () => { state.showFixed = !state.showFixed; viewMistakes(); } }, state.showFixed ? 'Hide' : 'Show'))),
          state.showFixed ? Object.keys(perDone).map(bid => {
            const b = bookById[bid] || { title: bid };
            const list = perDone[bid].slice().sort(byOrder);
            return h('div', { style: 'margin-top:12px' },
              h('div', { class: 'muted' }, b.title),
              h('div', { class: 'mist-grid' }, list.map(e => mistakeCard(e, () => startReview(null, keyOf(e), 'fixed')))));
          }) : null) : null,
        (todo.length || done.length) ? h('div', { class: 'center', style: 'margin-top:8px' },
          h('button', { class: 'secondary', onclick: () => { if (confirm('Delete the whole history, fixed ones too?')) { lsDel(MISTAKES); lsDel(MISTAKES_SESSION); viewMistakes(); } } }, 'Clear everything')) : null
      )
    );
  }

  // Build items for mistakes. `which` picks the still-to-fix set, the fixed set, or both.
  // Each item carries `prev` (the option picked last time it was wrong).
  function mistakeItems(onlyBook, which) {
    const m = getMistakes();
    const entries = Object.values(m)
      .filter(e => (!onlyBook || e.bookId === onlyBook)
        && (which === 'fixed' ? isFixed(e) : which === 'all' ? true : !isFixed(e)))
      .sort((a, c) => a.bookId.localeCompare(c.bookId) || a.testDir.localeCompare(c.testDir) || a.n - c.n);
    const ids = [...new Set(entries.map(e => e.bookId))];
    return Promise.all(ids.map(loadBook)).then(() => {
      const its = [];
      entries.forEach(e => {
        const b = loaded[e.bookId]; const t = b && b.tests.find(x => x.dir === e.testDir);
        const q = t && t.questions.find(x => x.n === e.n);
        if (!q) return;
        const it = makeItem(b, t, q); it.prev = e.pick || null; its.push(it);
      });
      return its;
    });
  }
  function startMistakes(onlyBook) {
    render(topBar('My Mistakes', backBtn(viewMistakes)), h('div', { class: 'page center muted' }, 'Loading…'));
    mistakeItems(onlyBook, 'todo').then(its => {
      if (!its.length) { viewMistakes(); return; }
      state.book = null;
      state.session = newSession('mistakes', MISTAKES_SESSION, 'My Mistakes', its, 'practice', false);
      save(); viewQuestion();
    }).catch(err => render(topBar('My Mistakes', backBtn(viewMistakes)), h('div', { class: 'page center' }, err.message)));
  }
  // Look through: no answering. Every puzzle shows the right answer, what was picked
  // last time, and the explanation. Nothing is saved and the list is left alone.
  function startReview(onlyBook, startKey, which) {
    render(topBar('Look through', backBtn(viewMistakes)), h('div', { class: 'page center muted' }, 'Loading…'));
    mistakeItems(onlyBook, which || 'todo').then(its => {
      if (!its.length) { viewMistakes(); return; }
      const sess = newSession('review', 'nnat:s:review', 'Look through', its, 'practice', false);
      sess.transient = true; sess.finished = true;
      its.forEach(it => { if (it.prev) sess.answers[it.key] = it.prev; });
      const i = its.findIndex(it => it.key === startKey);
      sess.idx = i < 0 ? 0 : i;
      state.book = null; state.session = sess; viewQuestion();
    }).catch(err => render(topBar('Look through', backBtn(viewMistakes)), h('div', { class: 'page center' }, err.message)));
  }

  // ---------- question ----------
  function exitToParent() {
    save(); stopTimer();
    const s = state.session;
    if (s.kind === 'mistakes' || s.kind === 'review') viewMistakes();
    else if (state.book) viewBook();
    else viewHome();
  }

  function viewQuestion() {
    const s = state.session; const qs = s.items; const q = qs[s.idx]; const total = qs.length;
    const chosen = s.answers[q.key];
    const showResult = s.finished || (s.mode === 'practice' && s.revealed[q.key]);
    const timerEl = s.mode === 'exam' && s.timerOn && !s.finished
      ? h('div', { id: 'timer', class: 'timer' + (s.timeLeft <= 60 ? ' low' : '') }, fmtTime(s.timeLeft == null ? EXAM_SECONDS : s.timeLeft))
      : (s.finished && s.kind !== 'review' ? h('button', { class: 'secondary', onclick: viewResults }, 'Results') : null);

    const letters = LETTERS.slice(0, q.nopts || 5);
    const opts = h('div', { class: 'options n' + letters.length }, letters.map((L, i) => {
      let cls = 'opt';
      if (showResult) { if (L === q.answer) cls += ' correct'; else if (L === chosen) cls += ' wrong'; }
      else if (L === chosen) cls += ' selected';
      const face = q.options
        ? h('span', { class: 'txt' }, q.options[i])                                   // number / word choice
        : h('img', { src: imgPath(q, 'abcde'[i]), alt: 'Option ' + L });             // picture choice
      return h('button', { class: cls + (q.options ? ' text' : ''), ...(showResult ? { disabled: '' } : {}), onclick: () => choose(q, L) },
        face, h('span', { class: 'letter' }, L));
    }));

    let feedback;
    const thing = q.options ? 'number' : 'picture';
    if (s.kind === 'review') {
      feedback = h('div', { class: 'feedback bad' },
        (q.prev ? 'Last time you picked ' + q.prev + '. ' : '') + 'The answer is ' + q.answer + '.',
        q.explanation ? h('div', { class: 'expl' }, q.explanation) : null,
        q.note ? h('div', { class: 'note' }, '🤔 ' + q.note) : null);
    } else if (showResult) {
      const ok = chosen === q.answer;
      feedback = h('div', { class: 'feedback ' + (ok ? 'ok' : 'bad') },
        ok ? '🎉 Correct!' : (chosen ? '❌ Not quite. The answer is ' + q.answer + '.' : 'Skipped. The answer is ' + q.answer + '.'),
        q.prev ? h('div', { class: 'expl' }, 'Last time you picked ' + q.prev + '.') : null,
        q.explanation ? h('div', { class: 'expl' }, q.explanation) : null,
        q.note ? h('div', { class: 'note' }, '🤔 ' + q.note) : null);
    } else if (chosen) {
      feedback = h('div', { class: 'feedback hint' }, 'You picked ' + chosen + '. Tap ' + (s.mode === 'practice' ? 'Check' : 'Next') + ', or tap another ' + thing + ' to change.');
    } else {
      feedback = h('div', { class: 'feedback hint' }, 'Tap the ' + thing + ' that fits the ?');
    }

    const isLast = s.idx === total - 1;
    let main;
    if (s.kind === 'review') {
      main = isLast ? h('button', { class: 'primary', onclick: viewMistakes }, 'Done ✓')
        : h('button', { class: 'primary', onclick: () => go(s.idx + 1) }, 'Next ▶');
    } else if (s.mode === 'practice' && !showResult) {
      main = h('button', { class: 'primary', ...(chosen ? {} : { disabled: '' }), onclick: () => check(q) }, 'Check ✓');
    } else if (isLast && !s.finished) {
      main = h('button', { class: 'primary', ...(chosen ? {} : { disabled: '' }), onclick: finish }, 'Finish ✓');
    } else if (isLast) {
      main = h('button', { class: 'primary', onclick: viewResults }, 'Results');
    } else {
      main = h('button', { class: 'primary', ...(chosen || s.finished ? {} : { disabled: '' }), onclick: () => go(s.idx + 1) }, 'Next ▶');
    }
    const nav = h('div', { class: 'nav' }, feedback,
      h('div', { class: 'nav-row' },
        h('button', { class: 'secondary', ...(s.idx === 0 ? { disabled: '' } : {}), onclick: () => go(s.idx - 1) }, '◀ Back'),
        h('span', { class: 'muted' }, (s.idx + 1) + ' / ' + total),
        main));

    // label: in a test the book's own number; in free/mistakes also say where it came from
    const where = s.kind === 'test' ? 'Puzzle ' + q.n
      : 'Puzzle ' + (s.idx + 1) + ' · ' + ((bookById[q.bookId] || {}).title || '') + ' · ' + q.testName + ' #' + q.n;
    render(
      topBar(s.title, backBtn(exitToParent), timerEl),
      h('div', { class: 'page quiz' },
        h('div', { class: 'progress' }, h('div', { style: 'width:' + Math.round(100 * (s.idx + 1) / total) + '%' })),
        h('div', { class: 'qnum' }, where),
        q.prompt ? h('div', { class: 'prompt' }, q.prompt) : null,
        q.stem ? h('div', { class: 'matrix' }, h('img', { src: imgPath(q, 'm'), alt: 'Puzzle', onload: layoutQuestion })) : null,
        opts, nav)
    );
    layoutQuestion();
    const nq = qs[s.idx + 1];
    // preload the next puzzle, but only the option letters it actually has
    if (nq) ['m'].concat(nq.options ? [] : 'abcde'.slice(0, nq.nopts || 5).split('')).forEach(x => { const im = new Image(); im.src = imgPath(nq, x); });
  }

  // Fit the puzzle to the screen so the child never has to scroll.
  function layoutQuestion() {
    const nav = document.querySelector('.nav'), page = document.querySelector('.page.quiz');
    const img = document.querySelector('.matrix img'), opts = document.querySelector('.options');
    if (!nav || !page || !opts) return;
    page.style.paddingBottom = (nav.offsetHeight + 12) + 'px';
    if (!img) return;
    const prompt = document.querySelector('.prompt');
    const fixed = 64 + 26 + 34 + 14 + 16 + (prompt ? prompt.offsetHeight + 10 : 0);
    const avail = window.innerHeight - fixed - opts.offsetHeight - nav.offsetHeight - 28;
    img.style.maxHeight = Math.max(140, avail) + 'px';
  }
  window.addEventListener('resize', layoutQuestion);

  // Tapping a picture only selects it; the child can tap another one to change their mind.
  function choose(q, L) {
    const s = state.session;
    if (s.finished) return;
    if (s.mode === 'practice' && s.revealed[q.key]) return;
    s.answers[q.key] = L; save(); viewQuestion();
  }
  // Practice mode: Check locks the answer and shows right/wrong.
  function check(q) {
    const s = state.session;
    if (!s.answers[q.key]) return;
    s.revealed[q.key] = true; noteResult(q, s.answers[q.key] === q.answer, s.answers[q.key]); save(); viewQuestion();
  }
  function go(i) {
    const s = state.session;
    if (i > s.idx && !s.finished && !s.answers[s.items[s.idx].key]) return;   // no skipping
    s.idx = Math.max(0, Math.min(s.items.length - 1, i)); save(); viewQuestion();
  }
  function finish() {
    const s = state.session;
    stopTimer(); s.finished = true;
    if (s.mode === 'exam') s.items.forEach(it => { if (s.answers[it.key]) noteResult(it, s.answers[it.key] === it.answer, s.answers[it.key]); });
    save(); viewResults();
  }

  // ---------- results ----------
  function viewResults() {
    const s = state.session; const qs = s.items; const { ok, total } = scoreInfo(s);
    const pct = Math.round(100 * ok / total);
    const msg = pct >= 90 ? '🌟 Amazing!' : pct >= 75 ? '🎉 Great job!' : pct >= 50 ? '👍 Good work!' : '💪 Keep practicing!';
    const wrong = total - ok;
    let again;
    if (s.kind === 'test') again = h('button', { class: 'primary', onclick: () => { lsDel(s.key); const t = state.book.tests.find(x => x.dir === qs[0].testDir); viewSetup('test', t); } }, 'Try again');
    else if (s.kind === 'free') again = h('button', { class: 'primary', onclick: () => { lsDel(s.key); viewSetup('free', null); } }, 'New puzzles 🎲');
    else again = h('button', { class: 'primary', onclick: () => { lsDel(s.key); viewMistakes(); } }, 'Back to mistakes');
    render(
      topBar(s.title, backBtn(exitToParent)),
      h('div', { class: 'page' },
        h('div', { class: 'card center' },
          h('div', { class: 'muted' }, 'Your score'),
          h('div', { class: 'score' }, ok + ' / ' + total),
          h('h2', { style: 'margin-top:10px' }, msg),
          h('div', { class: 'muted' }, s.kind === 'mistakes' ? (ok + ' fixed · ' + wrong + ' still to fix') : (wrong ? wrong + ' added to My Mistakes' : 'No mistakes!'))),
        h('div', { class: 'card' },
          h('h2', {}, 'Tap a puzzle to review it'),
          h('div', { class: 'dots' }, qs.map((q, i) => {
            const a = s.answers[q.key]; const cls = !a ? 'skip' : a === q.answer ? 'ok' : 'bad';
            return h('button', { class: 'dot ' + cls, onclick: () => go(i) }, String(s.kind === 'test' ? q.n : i + 1));
          })),
          h('div', { class: 'row', style: 'margin-top:14px' },
            h('span', { class: 'dot ok', style: 'height:28px;padding:0 10px' }, 'right'),
            h('span', { class: 'dot bad', style: 'height:28px;padding:0 10px' }, 'wrong'),
            h('span', { class: 'dot skip', style: 'height:28px;padding:0 10px' }, 'skipped'))),
        h('div', { class: 'row', style: 'justify-content:center' },
          again,
          wrong && s.kind !== 'mistakes' ? h('button', { class: 'secondary', onclick: viewMistakes }, '📕 My Mistakes') : null,
          h('button', { class: 'secondary', onclick: viewHome }, 'Home'))
      )
    );
  }

  // keyboard: A-E choose, Enter/Right = main button, Left = back
  document.addEventListener('keydown', e => {
    if (!state.session || !document.querySelector('.options')) return;
    const k = e.key.toUpperCase();
    if (LETTERS.includes(k)) { const q = items()[state.session.idx]; if (LETTERS.indexOf(k) < (q.nopts || 5)) choose(q, k); }
    else if (e.key === 'Enter' || e.key === 'ArrowRight') { const b = document.querySelector('.nav-row .primary'); if (b && !b.disabled) b.click(); }
    else if (e.key === 'ArrowLeft') go(state.session.idx - 1);
  });

  migrateMistakes();
  viewHome();
})();
