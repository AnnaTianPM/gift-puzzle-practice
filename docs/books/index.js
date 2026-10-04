// Registry of books available on the site. Each entry loads books/<id>/book.js
// `tests` lists the test names in order (test1, test2, ...) so the home page can show
// progress without loading the whole book. `tag` names the publisher, which is what
// tells two books for the same grade apart.
window.NNAT_BOOK_LIST = [
  { id: 'k-nnat-ab', ext: 'jpg', group: 'NNAT', title: 'NNAT Kindergarten', tag: 'Gateway', tagClass: 'gw', emoji: '🟡',
    subtitle: 'Level A/B · 3 tests × 50', tests: ['Test 1', 'Test 2', 'Test 3'] },
  { id: 'g1-nnat-b', ext: 'png', group: 'NNAT', title: 'NNAT Grade 1', tag: 'Origins', tagClass: 'or', emoji: '🔵',
    subtitle: 'Level B · 2 tests × 48', tests: ['Test 1', 'Test 2'] },
  { id: 'g2-nnat-c', ext: 'png', group: 'NNAT', title: 'NNAT Grade 2', tag: 'Origins', tagClass: 'or', emoji: '🟠',
    subtitle: 'Level C · 2 tests × 48', tests: ['Test 1', 'Test 2'] },
  { id: 'g2-nnat-c-gg', ext: 'jpg', group: 'NNAT', title: 'NNAT Grade 2', tag: 'Gateway', tagClass: 'gw', emoji: '🟧',
    subtitle: 'Level C · 3 tests × 50', tests: ['Test 1', 'Test 2', 'Test 3'] },
  { id: 'g3-nnat-d', ext: 'png', group: 'NNAT', title: 'NNAT Grade 3', tag: 'Origins', tagClass: 'or', emoji: '🟢',
    subtitle: 'Level D · 2 tests × 48', tests: ['Test 1', 'Test 2'] },
  { id: 'g34-nnat-d-gg', ext: 'jpg', group: 'NNAT', title: 'NNAT Grade 3–4', tag: 'Gateway', tagClass: 'gw', emoji: '🟩',
    subtitle: 'Level D · 3 tests × 48', tests: ['Test 1', 'Test 2', 'Test 3'] },
  { id: 'cogat-l9-math', ext: 'png', group: 'CogAT', title: 'CogAT Math · Grade 3', tag: 'Gateway', tagClass: 'gw', emoji: '🔢',
    subtitle: 'Level 9 · Number Puzzles 20 · Number Analogies 11', tests: ['Puzzles', 'Analogies'] },
  { id: 'cogat-l11-math', ext: 'png', group: 'CogAT', title: 'CogAT Math · Grade 5', tag: 'Gateway', tagClass: 'gw', emoji: '🧮',
    subtitle: 'Level 11 · Number Puzzles 10 · Number Analogies 11', tests: ['Puzzles', 'Analogies'] },
  { id: 'iowa-g1', ext: 'jpg', group: 'IOWA', title: 'IOWA Grade 1', tag: 'Read-aloud', tagClass: 'ra', emoji: '📖',
    subtitle: 'Math 3 sections · Language 4 sections', tests: ['Math 1', 'Math 2', 'Math 3', 'Language 1', 'Language 2', 'Language 3', 'Language 4'] },
  { id: 'gg-bonus', ext: 'png', group: 'Mixed', title: 'Gifted Sampler', tag: 'Gateway', tagClass: 'gw', emoji: '🎁',
    subtitle: 'Similarities · Shapes · Classification · Analogies · Patterns', tests: ['Similarities', 'Shapes', 'Classification', 'Analogies', 'Patterns', 'Bonus Pictures', 'Bonus Shapes'] },
];
