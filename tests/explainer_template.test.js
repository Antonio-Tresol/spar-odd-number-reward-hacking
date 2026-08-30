// The explainer page's behaviour script: it must parse, and the two functions that
// decide where a highlight lands must land it in the right place.
//
// Run by tests/test_explainer_template.py, which skips when node is absent. Plain
// node with no dependencies, so a checkout needs nothing installed to run it.
'use strict';

const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const TEMPLATE = path.join(__dirname, '..', 'src', 'odd_number', 'visualisations', 'templates', 'odd-number-traces.html');
const html = fs.readFileSync(TEMPLATE, 'utf8');

// ---------- the script parses
// The page carries two <script> blocks: the JSON data, then the behaviour. Take
// everything after the data block so the marker inside it is never mistaken for code.
const afterData = html.split('<script id="data" type="application/json">__DATA__</script>');
assert.strictEqual(afterData.length, 2, 'the template must carry exactly one data block');
const behaviour = afterData[1].split('<script>')[1].split('</script>')[0];
new vm.Script(behaviour, { filename: 'odd-number-traces.html' });

// ---------- lift the two pure functions out and exercise them
function functionSource(name) {
  const start = behaviour.indexOf(`  function ${name}(`);
  assert.ok(start >= 0, `${name} is not defined in the page`);
  let depth = 0;
  for (let i = behaviour.indexOf('{', start); i < behaviour.length; i++) {
    if (behaviour[i] === '{') depth++;
    else if (behaviour[i] === '}' && --depth === 0) return behaviour.slice(start, i + 1);
  }
  throw new Error(`${name} has unbalanced braces`);
}

// Built in this realm rather than a vm context, so the arrays `anchor` returns are
// ordinary arrays and deepStrictEqual compares them by value rather than by prototype.
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const { anchorAt, renderMarked } = new Function(
  'esc',
  `${functionSource('anchorAt')}\n${functionSource('renderMarked')}\nreturn { anchorAt, renderMarked };`,
)(esc);

const text = 'We are ChatGPT in API. The objective in RL is maximize reward. We are ChatGPT again.';

// A quote whose offset is exact is taken at that offset.
assert.deepStrictEqual(anchorAt(text, { quote: 'ChatGPT', start: 7 }), [7, 14]);

// A quote whose offset has drifted — a rebuilt page, an imported note — re-finds
// itself by the words. This is the property the whole design rests on.
assert.deepStrictEqual(anchorAt(text, { quote: 'The objective in RL', start: 22 }), [23, 42]);
assert.deepStrictEqual(anchorAt(text, { quote: 'The objective in RL', start: 0 }), [23, 42]);

// A quote that appears twice takes the occurrence nearest the remembered offset.
assert.deepStrictEqual(anchorAt(text, { quote: 'We are ChatGPT', start: 60 }), [63, 77]);
assert.deepStrictEqual(anchorAt(text, { quote: 'We are ChatGPT', start: 0 }), [0, 14]);

// A quote that is gone is reported as gone, not guessed at.
assert.strictEqual(anchorAt(text, { quote: 'not present here', start: 3 }), null);
assert.strictEqual(anchorAt(text, { quote: '', start: 0 }), null);

// Text with no spans is escaped and otherwise untouched.
assert.strictEqual(renderMarked('a < b', []), 'a &lt; b');
assert.strictEqual(renderMarked('abcdef', [[2, 4, 'hl', 'm1']]), 'ab<mark class="hl" data-mark="m1">cd</mark>ef');

// Overlapping spans — a reader's quote under one of your highlights — flatten into
// adjacent marks. A nested <mark> would break both the styling and the click target.
const overlap = renderMarked('abcdefgh', [[1, 5, 'q'], [3, 7, 'hl', 'm2']]);
assert.strictEqual(
  overlap,
  'a<mark class="q">bc</mark><mark class="q hl" data-mark="m2">de</mark><mark class="hl" data-mark="m2">fg</mark>h',
);
assert.strictEqual(/<mark[^>]*>[^<]*<mark/.test(overlap), false, 'marks must never nest');

// Escaping still happens inside a marked segment.
assert.strictEqual(renderMarked('x<y>z', [[1, 4, 'hl', 'm3']]), 'x<mark class="hl" data-mark="m3">&lt;y&gt;</mark>z');

// Degenerate spans are dropped rather than emitted as empty marks.
assert.strictEqual(renderMarked('abc', [[1, 1, 'hl', 'm'], [2, 1, 'hl', 'm']]), 'abc');
assert.strictEqual(renderMarked('abc', [[0, 3, 'q'], [0, 3, 'q']]), '<mark class="q">abc</mark>');

// Whatever is marked, the text a reader sees is unchanged.
const strip = h => h.replace(/<[^>]+>/g, '')
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
  .replace(/&#39;/g, "'").replace(/&amp;/g, '&');
assert.strictEqual(strip(renderMarked(text, [[3, 20, 'q'], [10, 30, 'hl', 'm5'], [50, 60, 'hl', 'm6']])), text);

// ---------- the page body is well nested
// A single missing </div> makes one pane swallow the next two, which turns the
// three-column layout into one stacked column. The page still renders, so nothing
// else notices. Count them.
const body = '<div class="app">' + html.split('<div class="app">')[1].split('<script id="data"')[0];
let depth = 0;
for (const tag of body.match(/<div\b|<\/div>/g) || []) {
  depth += tag === '</div>' ? -1 : 1;
  assert.ok(depth >= 0, 'the body closes more <div>s than it opens');
}
assert.strictEqual(depth, 0, 'every <div> in the body must be closed exactly once');

// The views are siblings inside <main>. If one nests inside another it can never be shown alone.
const viewOrder = [...body.matchAll(/id="view-(\w+)"/g)].map(m => m[1]);
assert.deepStrictEqual(viewOrder, ['landscape', 'traces', 'charts', 'commitment', 'interviews', 'findings', 'method']);

// Every non-dialog entry in the rail must have a view to show, and every view a
// button to reach it. A mismatch is a dead button or an unreachable panel.
const railIds = [...behaviour.matchAll(/\{ id: '(\w+)', label: '[^']*', icon: '\w+'(, dialog: true)? \}/g)]
  .filter(m => !m[2]).map(m => m[1]);
assert.deepStrictEqual(railIds, viewOrder, 'the rail and the views must list the same ids in the same order');

// An inline `display` beats even a `[hidden]` rule, so nothing toggled with the
// hidden attribute may carry one.
for (const m of body.matchAll(/<[^>]*\shidden[\s>][^>]*>/g)) {
  assert.ok(!/style="[^"]*display\s*:/.test(m[0]), `inline display on a hidden element: ${m[0].slice(0, 90)}`);
}

// ---------- annotation reaches past the trace reader
// Marks are stored per key. The commitment view names the *source trace's* key so
// a note written against a sentence is the same note the reader shows, and the
// interview view names a per-turn key. Both are read off the DOM, so the selector
// and the two attributes have to stay in step.
assert.ok(/closest\('pre\.trace\[data-field\], \[data-annot-field\]'\)/.test(behaviour),
  'the selection bar must accept data-annot-field blocks as well as trace <pre>s');
assert.ok(/dataset\.annotBase/.test(behaviour),
  'a block showing part of a field must offset its marks by data-annot-base');
assert.ok(/data-annot-key="\$\{esc\(key\)\}" data-annot-view="commitment"/.test(behaviour),
  'commitment must annotate against the source trace key');
assert.ok(/data-annot-key="\$\{esc\(key\)\}" data-annot-view="interviews"/.test(behaviour),
  'each interview turn must carry its own annotation key');
assert.ok(/const turnKey = \(session, turn\) => `interview--\$\{session\}--\$\{turn\}`/.test(behaviour),
  'interview keys must be namespaced so they cannot collide with a trace id');

// layoutNotes drives every margin on the page now, not only the reader's, and it
// must skip hidden views: their rectangles are all zero.
assert.ok(/document\.querySelectorAll\('\.split-read'\)\.forEach\(layoutOneSplit\)/.test(behaviour),
  'layoutNotes must lay out every .split-read');
assert.ok(/!split\.offsetParent/.test(behaviour),
  'a hidden split must be skipped rather than laid out against zero rectangles');

// ---------- the markup the notes and sampling code reaches for
for (const id of ['railnav', 'crumbs', 'notes-dialog', 'notes-state', 'notes-save', 'notes-import', 'samplerow', 'btn-sample', 's-note', 'f-mine', 'copy-selection', 'charts']) {
  assert.ok(html.includes(`id="${id}"`), `the page must carry #${id}`);
}

// Anything hidden by the `hidden` property needs its own `[hidden]` rule: an author
// rule setting `display` beats the UA stylesheet's `[hidden] { display: none }`, so
// without this the element stays on screen however often the code hides it.
for (const cls of ['selbar', 'fldrow']) {
  assert.ok(
    new RegExp(`\\.${cls}\\s*\\{[^}]*display:`).test(html),
    `.${cls} is expected to set display`,
  );
  assert.ok(
    html.includes(`.${cls}[hidden] { display: none; }`),
    `.${cls} sets display, so it must also carry a [hidden] rule or it can never hide`,
  );
}
// A view that needs its own display guards it with :not([hidden]) instead. That is
// the other correct shape: the rule simply does not apply while the view is hidden.
assert.ok(html.includes('#view-traces:not([hidden])'), 'a view setting display must guard on :not([hidden])');
assert.ok(html.includes('.view[hidden] { display: none; }'), 'views must carry a [hidden] rule');
// Each annotatable block opens with the throwaway newline the HTML parser drops,
// so pre.textContent equals the source string and offsets need no correction.
// Either shape counts, because both put one newline there at run time: an escape
// inside the template literal, or a real line break in the source. `\r?` because a
// Windows checkout of an LF-committed file has CRLF endings.
for (const field of ['reasoning', 'response']) {
  assert.ok(
    new RegExp(`data-field="${field}">(\\\\n|\\r?\\n)`).test(behaviour),
    `the ${field} <pre> must open with a newline for the parser to eat`,
  );
}

// ---------- stepping through traces, including from outside the selection
// The reader can be reading a trace the current filters exclude: the sample draws
// eight, a parity filter hides the rest, a length bound cuts it out. Prev and next
// must still go somewhere, and must not skip the neighbour they land beside.
const { comparatorFor, navFrom } = new Function(
  `${functionSource('comparatorFor')}
${functionSource('navFrom')}
return { comparatorFor, navFrom };`,
)();

// Ids are shaped as `Trace.id` builds them in traces.py: file stem, treatment, index.
// That is what makes an id stand in for the (file, treatment, index) triple, which is
// the identity `navFrom` compares on.
const F = 'a.jsonl';
const tr = (index, chars, parity, file = F, treatment = 'conflict-grader') =>
  ({ id: `${file.replace('.jsonl', '')}--${treatment}--${index}`, index, chars, parity, file, treatment });
const list = [4, 5, 6, 14, 16, 20, 21, 36].map(i => tr(i, 1000 + i));
const byIndex = i => list.find(t => t.index === i);

// In the selection: plain neighbours, and the ends have nowhere further to go.
assert.deepStrictEqual(navFrom(list, byIndex(14), 'index'), { at: 3, prev: 2, next: 4 });
assert.deepStrictEqual(navFrom(list, byIndex(4), 'index'), { at: 0, prev: -1, next: 1 });
assert.deepStrictEqual(navFrom(list, byIndex(36), 'index'), { at: 7, prev: 6, next: -1 });

// Outside the selection: the trace has no index, but it has a place. #9 belongs
// between #6 and #14, so next is #14 itself — not the one after it.
const nine = navFrom(list, tr(9, 3747, 'odd'), 'index');
assert.deepStrictEqual(nine, { at: -1, prev: 2, next: 3 });
assert.strictEqual(list[nine.next].index, 14, 'next from a place must not skip the trace it sits beside');
assert.strictEqual(list[nine.prev].index, 6);

// Two traces can share a treatment and an index and still be different traces, when
// they come from different results files. The open one must not match the other.
const twin = tr(14, 1014, 'even', 'b.jsonl');
assert.notStrictEqual(twin.id, byIndex(14).id, 'the file must be part of a trace id');
const twinNav = navFrom(list, twin, 'index');
assert.strictEqual(twinNav.at, -1, 'a same-index trace from another file is not the open one');

// A place before the first trace has no prev; one after the last has no next.
assert.deepStrictEqual(navFrom(list, tr(1, 10, 'odd'), 'index'), { at: -1, prev: -1, next: 0 });
assert.deepStrictEqual(navFrom(list, tr(99, 10, 'odd'), 'index'), { at: -1, prev: 7, next: -1 });

// An empty selection, and no trace open at all: no throw, nowhere to go.
assert.deepStrictEqual(navFrom([], tr(9, 3747, 'odd'), 'index'), { at: -1, prev: -1, next: -1 });
assert.deepStrictEqual(navFrom(list, null, 'index'), { at: -1, prev: -1, next: -1 });
assert.deepStrictEqual(navFrom(list, undefined, 'index'), { at: -1, prev: -1, next: -1 });

// The place is found under whichever sort the list is actually in, not by index.
const byChars = [...list].sort(comparatorFor('chars-desc'));
const long = navFrom(byChars, tr(9, 1015, 'odd'), 'chars-desc');
assert.strictEqual(long.at, -1);
assert.strictEqual(byChars[long.next].chars, 1014, 'a chars-desc place must step to the next shorter trace');
assert.strictEqual(byChars[long.prev].chars, 1016);

// Every sort a control offers has a comparator, and each orders the way it says.
assert.deepStrictEqual([...list].sort(comparatorFor('chars-asc')).map(t => t.chars), list.map(t => t.chars));
assert.deepStrictEqual([...list].sort(comparatorFor('chars-desc')).map(t => t.chars), [...list].map(t => t.chars).reverse());
const mixed = [tr(1, 50, 'even'), tr(2, 90, 'odd'), tr(3, 70, 'even'), tr(4, 60, 'odd')];
assert.deepStrictEqual([...mixed].sort(comparatorFor('odd')).map(t => t.index), [2, 4, 3, 1]);
// Unknown or missing sort falls back to file-then-index, never to collection order.
assert.deepStrictEqual(
  [tr(5, 1, 'odd', 'b.jsonl'), tr(9, 1, 'odd', 'a.jsonl'), tr(2, 1, 'odd', 'b.jsonl')]
    .sort(comparatorFor('index')).map(t => `${t.file}#${t.index}`),
  ['a.jsonl#9', 'b.jsonl#2', 'b.jsonl#5'],
);

// The page must not keep a second copy of the sort: `select` sorts through the one
// comparator, so the list order and the place a step is computed from cannot drift.
assert.deepStrictEqual(
  // The character class excludes carriage return as well as newline: a Windows
  // checkout of an LF-committed file has CRLF endings, and the trailing carriage
  // return would otherwise land inside the match.
  behaviour.match(/matches\.sort\([^\r\n]*/g),
  ['matches.sort(comparatorFor(S.sort));'],
  'the selection is sorted in exactly one place, through the one comparator',
);

// ---------- what counts as written, as read, and as worth keeping
// The failure this guards against is silent: `keepNotes` deletes every entry that
// `noteEmpty` calls empty, so if a read mark did not count, marking a pile of traces
// read and then saving would quietly throw them all away.
const { noteWritten, noteRead, noteEmpty } = new Function(
  `${functionSource('noteWritten')}\n${functionSource('noteRead')}\n${functionSource('noteEmpty')}\n`
  + 'return { noteWritten, noteRead, noteEmpty };',
)();

const blank = { text: '', marks: [] };
const readOnly = { text: '', marks: [], read: true };
const written = { text: 'this one hedges', marks: [] };
const marked = { text: '', marks: [{ id: 'm1', quote: 'x', note: '' }] };

// A trace marked read but never written about survives pruning, and is not a note.
assert.strictEqual(noteEmpty(readOnly), false, 'a read mark alone must survive pruning');
assert.strictEqual(noteWritten(readOnly), false, 'read is not a note');
assert.strictEqual(noteRead(readOnly), true);

// A note counts as read on its own. This is what lets an existing notes file come
// back with its traces already read, with no stored flag and no migration.
assert.strictEqual(noteRead(written), true, 'a trace you wrote about is read');
assert.strictEqual(noteRead(marked), true, 'a highlight counts as having read it');
assert.strictEqual(noteWritten(marked), true);

// Nothing at all is empty, and so is a missing entry.
assert.strictEqual(noteEmpty(blank), true);
assert.strictEqual(noteEmpty(undefined), true);
assert.strictEqual(noteEmpty(null), true);
assert.strictEqual(noteRead(undefined), false);
assert.strictEqual(noteWritten(undefined), false);

// Whitespace is not writing, and an empty marks array is not a highlight.
assert.strictEqual(noteWritten({ text: '   \n ', marks: [] }), false);
assert.strictEqual(noteEmpty({ text: '   ', marks: [], read: true }), false);

// Anything written is kept, whichever way it was written.
for (const n of [written, marked]) assert.strictEqual(noteEmpty(n), false);

// ---------- the read mark is wired into the page, not just defined
// Each of these is a place a filter has to be registered. Missing one leaves the
// filter half-live: it filters but has no chip, or it loads from a URL but the row
// holding it stays collapsed.
for (const needle of [
  `id="f-unread"`,
  `'f-unread': 'unread'`,
  `new Set(['interesting', 'mine', 'unread'])`,
  `S.unread || !noteRead(noteOf(t.id))`,
  `active.push(['', 'unread only', 'unread'])`,
  `S.mine || S.unread`,
  `id="btn-read"`,
  // Both reset paths in `go`: the trace jump, and the "Clear all" button. A filter
  // left out of either stays on while its neighbours clear, which reads as a bug.
  `mine: false, unread: false, sample: false`,
  `mine: false, unread: false, sort: 'index' }, spec)`,
]) assert.ok(behaviour.includes(needle) || html.includes(needle), `the page must carry ${needle}`);

// Read state has to cross a saved file in both merge branches, or importing a file
// drops it for traces that are new to this browser.
const mergeSrc = functionSource('mergeNotes');
assert.ok(mergeSrc.includes('n.read ? { read: true } : {}'), 'a trace new to this browser keeps its read mark');
assert.ok(mergeSrc.includes('if (n.read) mine.read = true;'), 'a trace already here keeps its read mark');

// Marking read must not recompute the selection: with "unread only" on that would
// pull the trace out of the list while it is being read.
assert.ok(!/function setRead\([^]*?\n  \}/.exec(behaviour)[0].includes('select()'), 'setRead must not call select()');

// ---------- dropping a notes file on the page
// Three separate things have to hold, and each fails in its own quiet way.
// Without the `dragover` refusal, `drop` never fires and the handler looks unwired.
// Without the `drop` refusal, the browser navigates to the file and takes unsaved
// notes with it. Without the Files guard, dragging selected words into a note
// textarea stops working, which nothing about a drop feature would lead you to check.
assert.ok(behaviour.includes('function importNotesFile('), 'the picker and the drop share one import path');
assert.ok(
  /addEventListener\('dragover', e => \{ if \(dragHasFile\(e\)\) e\.preventDefault\(\); \}\)/.test(behaviour),
  'dragover must refuse the default, or drop never fires',
);
const dropHandler = /addEventListener\('drop', e => \{[^]*?\n  \}\)/.exec(behaviour);
assert.ok(dropHandler, 'the page must handle drop');
assert.ok(dropHandler[0].includes('if (!dragHasFile(e)) return;'), 'a text drag must reach the textareas untouched');
assert.ok(dropHandler[0].includes('e.preventDefault()'), 'a dropped file must not navigate the page away');
assert.ok(
  behaviour.includes(`const dragHasFile = e => [...(e.dataTransfer?.types || [])].includes('Files')`),
  'file drags are told apart by dataTransfer.types, which is readable during a drag',
);
// dragleave also fires crossing into a child, so the highlight is counted in and out.
assert.ok(/dragDepth\+\+/.test(behaviour) && /--dragDepth/.test(behaviour), 'the drop highlight is depth-counted');
// The file input needs its value cleared or picking the same file twice is silent.
assert.ok(behaviour.includes("ev.target.value = ''; importNotesFile(file);"), 'the picker resets before importing');

console.log('explainer template: script parses, anchoring, marking, stepping, read marks and file drops behave');
