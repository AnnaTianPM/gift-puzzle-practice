/* Puzzle Practice - static quiz app for NNAT-style picture puzzles. No build step. */
(function () {
  const LETTERS = ['A', 'B', 'C', 'D', 'E'];
  const app = document.getElementById('app');
  const books = window.NNAT_BOOK_LIST || [];
  const state = {
    view: 'home', book: null, test: null,
    mode: 'practice', timerOn: true, seconds: 30 * 60,
    idx: 0, answers: {}, revealed: {}, finished: false, timeLeft: null,
    timerHandle: null,
  };

  // ---------- data loading ----------
  function loadBook(id) {
    return new Promise((resolve, reject) => {
      if (window.NNAT_BOOKS && window.NNAT_BOOKS[id]) return resolve(window.NNAT_BOOKS[id]);
      const s = document.createElement('script');
      s.src = 'books/' + id + '/book.js?v=' + Date.now();
      s.onload = () => resolve(window.NNAT_BOOKS[id]);
      s.onerror = () => reject(new Error('Could not load book ' + id));
      document.head.appendChild(s);
    });
  }
  function imgPath(q, suffix) {
    return 'books/' + state.book.id + '/' + state.test.dir + '/q' + String(q.n).padStart(2, '0') + '_' + suffix + '.png';
  }

  // ---------- persistence ----------
  function storeKey() { return 'nnat:' + state.book.id + ':' + state.test.dir; }
  function save() {
    try {
      localStorage.setItem(storeKey(), JSON.stringify({
        mode: state.mode, timerOn: state.timerOn, idx: state.idx, answers: state.answers,
        revealed: state.revealed, finished: state.finished, timeLeft: state.timeLeft, at: Date.now(),
      }));
    } catch (e) { /* storage unavailable */ }
  }
  function loadSaved() {
    try { const raw = localStorage.getItem(storeKey()); return raw ? JSON.parse(raw) : null; } catch (e) { return null; }
  }
  function clearSaved() { try { localStorage.removeItem(storeKey()); } catch (e) { /* ignore */ } }

  // ---------- helpers ----------
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const k in attrs || {}) {
      if (k === 'class') el.className = attrs[k];
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), attrs[k]);
      else if (k === 'html') el.innerHTML = attrs[k];
      else el.setAttribute(k, attrs[k]);
    }
    for (const c of children.flat()) if (c != null) el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    return el;
  }
  function render(...nodes) { app.replaceChildren(...nodes); window.scrollTo(0, 0); }
  function fmtTime(s) { const m = Math.floor(s / 60), r = s % 60; return m + ':' + String(r).padStart(2, '0'); }
  function questions() { return state.test.questions; }
  function scoreInfo() {
    const qs = questions(); let ok = 0, done = 0;
    qs.forEach(q => { const a = state.answers[q.n]; if (a) { done++; if (a === q.answer) ok++; } });
    return { ok, done, total: qs.length };
  }

  // ---------- timer ----------
  function stopTimer() { if (state.timerHandle) { clearInterval(state.timerHandle); state.timerHandle = null; } }
  function startTimer() {
    stopTimer();
    if (!(state.mode === 'exam' && state.timerOn) || state.finished) return;
    if (state.timeLeft == null) state.timeLeft = state.seconds;
    state.timerHandle = setInterval(() => {
      state.timeLeft--;
      const el = document.getElementById('timer');
      if (el) { el.textContent = fmtTime(state.timeLeft); el.classList.toggle('low', state.timeLeft <= 60); }
      if (state.timeLeft % 5 === 0) save();
      if (state.timeLeft <= 0) { finish(); }
    }, 1000);
  }

  // ---------- views ----------
  function topBar(title, left, right) {
    return h('div', { class: 'bar' }, left || h('div', { class: 'spacer' }), h('div', { class: 'title' }, title), right || h('div', { class: 'spacer' }));
  }
  function backBtn(fn) { return h('button', { class: 'icon-btn', onclick: fn, title: 'Back' }, '←'); }

  function viewHome() {
    stopTimer();
    render(
      topBar('Puzzle Practice'),
      h('div', { class: 'page' },
        h('h1', { class: 'center' }, 'Pick a book'),
        h('p', { class: 'center muted' }, 'Choose a book, then a practice test.'),
        books.map(b => h('button', { class: 'big-btn', onclick: () => openBook(b) },
          h('span', { class: 'emoji' }, b.emoji || '📘'),
          h('span', {}, h('div', { class: 'label' }, b.title), h('div', { class: 'sub' }, b.subtitle || ''))))
      )
    );
  }

  function openBook(b) {
    render(topBar(b.title, backBtn(viewHome)), h('div', { class: 'page center muted' }, 'Loading…'));
    loadBook(b.id).then(data => { state.book = Object.assign({}, b, data); viewBook(); })
      .catch(err => render(topBar(b.title, backBtn(viewHome)), h('div', { class: 'page center' }, err.message)));
  }

  function viewBook() {
    const b = state.book;
    render(
      topBar(b.title, backBtn(viewHome)),
      h('div', { class: 'page' },
        h('h1', { class: 'center' }, 'Pick a test'),
        b.tests.map((t, i) => {
          state.test = t; const saved = loadSaved(); state.test = null;
          let sub = t.questions.length + ' questions';
          if (saved && saved.finished) { const ok = Object.keys(saved.answers).filter(n => saved.answers[n] === t.questions.find(q => q.n == n).answer).length; sub += ' · Last score ' + ok + '/' + t.questions.length; }
          else if (saved && Object.keys(saved.answers).length) sub += ' · In progress (' + Object.keys(saved.answers).length + ' answered)';
          return h('button', { class: 'big-btn', onclick: () => { state.test = t; viewSetup(); } },
            h('span', { class: 'emoji' }, ['1️⃣', '2️⃣', '3️⃣', '4️⃣'][i] || '📝'),
            h('span', {}, h('div', { class: 'label' }, t.name), h('div', { class: 'sub' }, sub)));
        })
      )
    );
  }

  function viewSetup() {
    const saved = loadSaved();
    const modeCard = (mode, title, desc) => h('div', { class: 'choice' + (state.mode === mode ? ' on' : ''), onclick: () => { state.mode = mode; viewSetup(); } },
      h('b', {}, title), h('span', { class: 'muted' }, desc));
    const resume = saved && Object.keys(saved.answers).length && !saved.finished
      ? h('div', { class: 'resume' }, h('div', {}, h('b', {}, 'You have an unfinished test.'), ' ', Object.keys(saved.answers).length + ' of ' + questions().length + ' answered.'),
        h('div', { class: 'row', style: 'margin-top:10px' },
          h('button', { class: 'primary', onclick: () => resumeSaved(saved) }, 'Continue'),
          h('button', { class: 'secondary', onclick: () => { clearSaved(); viewSetup(); } }, 'Start over')))
      : null;
    const review = saved && saved.finished
      ? h('div', { class: 'resume' }, h('div', {}, h('b', {}, 'Finished last time.'), ' You can review the answers.'),
        h('div', { class: 'row', style: 'margin-top:10px' },
          h('button', { class: 'secondary', onclick: () => { resumeSaved(saved); viewResults(); } }, 'Review answers'),
          h('button', { class: 'secondary', onclick: () => { clearSaved(); viewSetup(); } }, 'Clear result')))
      : null;
    render(
      topBar(state.test.name, backBtn(viewBook)),
      h('div', { class: 'page' },
        resume, review,
        h('div', { class: 'card' },
          h('h2', {}, 'How do you want to play?'),
          h('div', { class: 'choice-grid' },
            modeCard('practice', '🎯 Practice', 'See if you are right after each puzzle, with a hint.'),
            modeCard('exam', '⏱️ Test', 'Answer all puzzles first, then see your score.')),
          state.mode === 'exam' ? h('label', { class: 'check' },
            h('input', { type: 'checkbox', ...(state.timerOn ? { checked: '' } : {}), onchange: e => { state.timerOn = e.target.checked; } }),
            h('span', {}, '30 minute timer')) : null),
        h('div', { class: 'center' }, h('button', { class: 'primary', onclick: startNew }, 'Start ▶'))
      )
    );
  }

  function resumeSaved(saved) {
    state.mode = saved.mode; state.timerOn = saved.timerOn; state.idx = saved.idx || 0;
    state.answers = saved.answers || {}; state.revealed = saved.revealed || {};
    state.finished = !!saved.finished; state.timeLeft = saved.timeLeft;
    if (!state.finished) { startTimer(); viewQuestion(); }
  }
  function startNew() {
    state.idx = 0; state.answers = {}; state.revealed = {}; state.finished = false; state.timeLeft = null;
    clearSaved(); save(); startTimer(); viewQuestion();
  }

  function viewQuestion() {
    const qs = questions(); const q = qs[state.idx]; const total = qs.length;
    const chosen = state.answers[q.n];
    const showResult = state.finished || (state.mode === 'practice' && state.revealed[q.n]);
    const timerEl = state.mode === 'exam' && state.timerOn && !state.finished
      ? h('div', { id: 'timer', class: 'timer' + (state.timeLeft <= 60 ? ' low' : '') }, fmtTime(state.timeLeft == null ? state.seconds : state.timeLeft))
      : (state.finished ? h('button', { class: 'secondary', onclick: viewResults }, 'Results') : null);

    const opts = h('div', { class: 'options' }, LETTERS.map((L, i) => {
      let cls = 'opt';
      if (showResult) { if (L === q.answer) cls += ' correct'; else if (L === chosen) cls += ' wrong'; }
      else if (L === chosen) cls += ' selected';
      return h('button', { class: cls, ...(showResult ? { disabled: '' } : {}), onclick: () => choose(q, L) },
        h('img', { src: imgPath(q, 'abcde'[i]), alt: 'Option ' + L }), h('span', { class: 'letter' }, L));
    }));

    let feedback = null;
    if (showResult) {
      const ok = chosen === q.answer;
      feedback = h('div', { class: 'feedback ' + (ok ? 'ok' : 'bad') },
        ok ? '🎉 Correct!' : (chosen ? '❌ Not quite. The answer is ' + q.answer + '.' : 'Skipped. The answer is ' + q.answer + '.'),
        q.explanation ? h('div', { class: 'expl' }, q.explanation) : null);
    } else if (chosen) {
      feedback = h('div', { class: 'feedback hint' }, state.mode === 'practice'
        ? 'You picked ' + chosen + '. Tap Check, or tap another picture to change.'
        : 'You picked ' + chosen + '. Tap Next, or tap another picture to change.');
    } else {
      feedback = h('div', { class: 'feedback hint' }, 'Tap the picture that fits the ?');
    }

    // Main button: the child confirms with it. Practice: Check reveals the answer, then Next.
    const isLast = state.idx === total - 1;
    let main;
    if (state.mode === 'practice' && !showResult) {
      main = h('button', { class: 'primary', ...(chosen ? {} : { disabled: '' }), onclick: () => check(q) }, 'Check ✓');
    } else if (isLast && !state.finished) {
      main = h('button', { class: 'primary', ...(chosen ? {} : { disabled: '' }), onclick: finish }, 'Finish ✓');
    } else if (isLast) {
      main = h('button', { class: 'primary', onclick: viewResults }, 'Results');
    } else {
      main = h('button', { class: 'primary', ...(chosen || state.finished ? {} : { disabled: '' }), onclick: () => go(state.idx + 1) }, 'Next ▶');
    }
    const nav = h('div', { class: 'nav' },
      feedback,
      h('div', { class: 'nav-row' },
        h('button', { class: 'secondary', ...(state.idx === 0 ? { disabled: '' } : {}), onclick: () => go(state.idx - 1) }, '◀ Back'),
        h('span', { class: 'muted' }, (state.idx + 1) + ' / ' + total),
        main));

    render(
      topBar(state.test.name, backBtn(() => { save(); stopTimer(); viewSetup(); }), timerEl),
      h('div', { class: 'page quiz' },
        h('div', { class: 'progress' }, h('div', { style: 'width:' + Math.round(100 * (state.idx + 1) / total) + '%' })),
        h('div', { class: 'qnum' }, 'Puzzle ' + q.n),
        h('div', { class: 'matrix' }, h('img', { src: imgPath(q, 'm'), alt: 'Puzzle ' + q.n, onload: layoutQuestion })),
        opts, nav)
    );
    layoutQuestion();
    // preload next question's images
    const nq = qs[state.idx + 1];
    if (nq) ['m', 'a', 'b', 'c', 'd', 'e'].forEach(s => { const im = new Image(); im.src = imgPath(nq, s); });
  }

  // Fit the puzzle to the screen so the child never has to scroll.
  function layoutQuestion() {
    const nav = document.querySelector('.nav'), page = document.querySelector('.page.quiz');
    const img = document.querySelector('.matrix img'), opts = document.querySelector('.options');
    if (!nav || !page || !img || !opts) return;
    page.style.paddingBottom = (nav.offsetHeight + 12) + 'px';
    const fixed = 64 /* top bar */ + 26 /* progress */ + 34 /* label */ + 14 /* gap */ + 16 /* padding */;
    const avail = window.innerHeight - fixed - opts.offsetHeight - nav.offsetHeight - 28;
    img.style.maxHeight = Math.max(140, avail) + 'px';
  }
  window.addEventListener('resize', layoutQuestion);

  // Tapping a picture only selects it; the child can tap another one to change their mind.
  function choose(q, L) {
    if (state.finished) return;
    if (state.mode === 'practice' && state.revealed[q.n]) return;
    state.answers[q.n] = L; save(); viewQuestion();
  }
  // Practice mode: Check locks the answer and shows right/wrong.
  function check(q) {
    if (!state.answers[q.n]) return;
    state.revealed[q.n] = true; save(); viewQuestion();
  }
  function go(i) {
    // No skipping: moving forward requires an answer to the current puzzle.
    if (i > state.idx && !state.finished && !state.answers[questions()[state.idx].n]) return;
    state.idx = Math.max(0, Math.min(questions().length - 1, i)); save(); viewQuestion();
  }
  function finish() { stopTimer(); state.finished = true; save(); viewResults(); }

  function viewResults() {
    const qs = questions(); const { ok, total } = scoreInfo();
    const pct = Math.round(100 * ok / total);
    const msg = pct >= 90 ? '🌟 Amazing!' : pct >= 75 ? '🎉 Great job!' : pct >= 50 ? '👍 Good work!' : '💪 Keep practicing!';
    render(
      topBar(state.test.name, backBtn(viewSetup)),
      h('div', { class: 'page' },
        h('div', { class: 'card center' },
          h('div', { class: 'muted' }, 'Your score'),
          h('div', { class: 'score' }, ok + ' / ' + total),
          h('h2', { style: 'margin-top:10px' }, msg),
          h('div', { class: 'muted' }, pct + '% correct')),
        h('div', { class: 'card' },
          h('h2', {}, 'Tap a puzzle to review it'),
          h('div', { class: 'dots' }, qs.map((q, i) => {
            const a = state.answers[q.n]; const cls = !a ? 'skip' : a === q.answer ? 'ok' : 'bad';
            return h('button', { class: 'dot ' + cls, onclick: () => go(i) }, String(q.n));
          })),
          h('div', { class: 'row', style: 'margin-top:14px' },
            h('span', { class: 'dot ok', style: 'height:28px;padding:0 10px' }, 'right'),
            h('span', { class: 'dot bad', style: 'height:28px;padding:0 10px' }, 'wrong'),
            h('span', { class: 'dot skip', style: 'height:28px;padding:0 10px' }, 'skipped'))),
        h('div', { class: 'row center', style: 'justify-content:center' },
          h('button', { class: 'primary', onclick: () => { clearSaved(); viewSetup(); } }, 'Try again'),
          h('button', { class: 'secondary', onclick: viewHome }, 'Home'))
      )
    );
  }

  // keyboard: A-E choose, arrows navigate
  document.addEventListener('keydown', e => {
    if (state.view !== 'q' && !document.querySelector('.options')) return;
    const k = e.key.toUpperCase();
    if (LETTERS.includes(k)) { const q = questions()[state.idx]; choose(q, k); }
    else if (e.key === 'Enter' || e.key === 'ArrowRight') { const b = document.querySelector('.nav-row .primary'); if (b && !b.disabled) b.click(); }
    else if (e.key === 'ArrowLeft') go(state.idx - 1);
  });

  viewHome();
})();
