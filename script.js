'use strict';

// Actual published files in MyPCBench_final_video_64/cua_only-f001 (checked 2026-10-12).
const episodeRoot = 'https://huggingface.co/datasets/yuqi777/WorkDemo-350/';
const episodePath = 'MyPCBench_final_video_64/cua_only-f001/';
const evidenceImages = [
  '0001_click_00001472ms_lclick_00_01_472_at_1627_183.png',
  '0002_click_00004424ms_lclick_00_04_424_at_2526_359.png',
  '0003_click_00012993ms_lclick_00_12_993_at_2344_344.png',
  '0004_click_00015409ms_lclick_00_15_409_at_2281_346.png',
  '0005_click_00020222ms_lclick_00_20_222_at_500_1213.png',
  '0006_click_00023410ms_lclick_00_23_410_at_811_1345.png',
  '0007_click_00029081ms_lclick_00_29_081_at_1756_1329.png',
  '0008_click_00035987ms_lclick_00_35_987_at_1719_1088.png',
  '0009_click_00042865ms_lclick_00_42_865_at_2161_1388.png',
  '0010_double_click_00046233ms_ldoubleclick_00_46_090_00_46_233_at_1588_367.png',
  '0011_click_00051381ms_lclick_00_51_381_at_1801_1108.png'
];
const files = {
  evidence: {symbol: '▧', title: 'Screenshots and their indexes.', description: 'This folder contains 11 PNG screenshots and two index files. The indexes connect each image to its timestamp, click coordinates, and matched action.', path: 'evidence/', folder: true, children: [
    ['manifest.json', '11 evidence events with image filenames, timestamps, coordinates, and action captions.'],
    ['image_actions.jsonl', 'One record per image, linking the screenshot to its matched action.']
  ], images: evidenceImages},
  trace: {symbol: '↖', title: 'Actions and raw input events.', description: 'Both trace files live inside this folder. Structured actions and the original input log preserve two views of the recorded interaction.', path: 'trace/', folder: true, children: [
    ['actions.jsonl', '15 structured actions; adjacent typing and scroll events are merged.'],
    ['keylog.log', '40 input events with timestamps, messages, and window context, preceded by comment metadata.']
  ]},
  episode: {symbol: '{ }', title: 'The episode at a glance.', description: 'Session metadata, recording duration, event counts, and relative paths to the task, video, summary, trace, and evidence files. This episode records 54.175 seconds, 15 actions, and 11 evidence images.', path: 'episode.json'},
  summary: {symbol: '≡', title: 'A readable recording timeline.', description: 'A Markdown session summary with the recording duration and counts, followed by a timestamped timeline of control events, keyframes, and actions.', path: 'summary.md'},
  task: {symbol: '{ }', title: 'The task and its context.', description: 'The task ID, app, apps involved, category, difficulty, and instruction. In this example: check in for the next Dinoco Airlines flight, verify that the boarding pass renders, and download it.', path: 'task.json'},
  video: {symbol: '▷', title: 'The screen recording.', description: 'The MP4 recording of this demonstration, stored at the episode root. It preserves the visual workflow and transitions between the evidence screenshots.', path: 'video.mp4'}
};

function episodeUrl(path, folder = false) {
  return `${episodeRoot}${folder ? 'tree' : 'blob'}/main/${episodePath}${path}`;
}

function fileItem(path, description = '') {
  const item = document.createElement('li');
  const link = document.createElement('a');
  link.href = episodeUrl(path); link.target = '_blank'; link.rel = 'noopener noreferrer';
  link.textContent = path.split('/').pop(); item.append(link);
  if (description) { const text = document.createElement('p'); text.textContent = description; item.append(text); }
  return item;
}

function selectFile(key, focus = false) {
  const file = files[key]; if (!file) return;
  document.querySelectorAll('[data-file]').forEach(button => {
    const active = button.dataset.file === key;
    button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1;
    if (active && focus) button.focus();
  });
  document.getElementById('file-panel').setAttribute('aria-labelledby', `file-${key}-tab`);
  document.getElementById('file-symbol').textContent = file.symbol;
  document.getElementById('file-title').textContent = file.title;
  document.getElementById('file-description').textContent = file.description;
  document.getElementById('file-path').textContent = file.path;
  const openLink = document.getElementById('file-open');
  openLink.href = episodeUrl(file.path, file.folder);
  openLink.setAttribute('aria-label', `Open ${file.path} on Hugging Face`);
  const contents = document.getElementById('file-contents'); contents.replaceChildren();
  if (file.children) {
    const list = document.createElement('ul'); list.className = 'episode-file-list';
    file.children.forEach(([name, description]) => list.append(fileItem(file.path + name, description)));
    contents.append(list);
  }
  if (file.images) {
    const disclosure = document.createElement('details'); disclosure.className = 'episode-image-files';
    const summary = document.createElement('summary'); summary.textContent = `${file.images.length} screenshot files (.png)`;
    const list = document.createElement('ul'); list.className = 'episode-file-list';
    file.images.forEach(name => list.append(fileItem(file.path + name)));
    disclosure.append(summary, list); contents.append(disclosure);
  }
}

function configureTabs(selector, keyName, select, vertical = false) {
  const buttons = [...document.querySelectorAll(selector)];
  buttons.forEach((button, index) => {
    button.addEventListener('click', () => select(button.dataset[keyName]));
    button.addEventListener('keydown', event => {
      let next;
      if (event.key === (vertical ? 'ArrowDown' : 'ArrowRight')) next = (index + 1) % buttons.length;
      else if (event.key === (vertical ? 'ArrowUp' : 'ArrowLeft')) next = (index - 1 + buttons.length) % buttons.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = buttons.length - 1;
      if (next !== undefined) { event.preventDefault(); select(buttons[next].dataset[keyName], true); }
    });
  });
}
configureTabs('[data-file]', 'file', selectFile, true);

// Paper v1, Tables 2 and 3. Each row follows the methods array below.
const modelNames = ['GPT-5.5', 'Opus-4.8', 'Qwen3.5-35B-A3B', 'Qwen3.5-9B'];
const methods = ['No Skill', 'ShowUI-Aloha', 'Demo2Tutorial', 'Work2Skill'];
const colors = ['baseline', 'aloha', 'd2t', 'blue'];
const benchmarks = {
  mypc: {
    title: 'MyPCBench',
    description: '64 MyPCBench Bounded Action tasks. The same model induces skills and executes tasks. Results from Table 2.',
    score: [[74.73, 77.48, 75.25, 85.27], [81.53, 79.27, 81.28, 86.20], [38.38, 37.69, 40.61, 44.56], [24.27, 26.61, 27.75, 34.11]],
    sr: [[23.44, 37.50, 37.50, 48.44], [42.19, 34.38, 42.19, 50.00], [9.38, 12.50, 9.38, 20.31], [6.25, 3.13, 6.25, 12.50]]
  },
  osworld: {
    title: 'OSWorld-Verified subset',
    description: 'Selected 286-task OSWorld-Verified subset, not the full benchmark. See the dataset provenance disclosure. Results from Table 2.',
    score: [[74.47, 72.57, 80.32, 81.97], [79.23, 78.91, 80.66, 82.34], [32.52, 31.08, 33.93, 36.36], [27.48, 24.81, 26.45, 33.41]],
    sr: [[70.98, 69.93, 76.22, 78.67], [77.97, 76.57, 78.67, 79.37], [32.17, 30.42, 32.52, 36.01], [26.92, 24.13, 25.52, 32.52]]
  },
  jitter: {
    title: 'MyPCBench Jitter',
    description: '64 paired variants with changed requirements in the same applications. Original skills are reused without further induction. Results from Table 3.',
    score: [[73.45, 75.50, 73.03, 81.75], [83.30, 82.66, 81.44, 87.23], [42.94, 41.19, 46.92, 51.58], [27.80, 31.97, 30.66, 36.25]],
    sr: [[37.50, 42.19, 35.94, 46.88], [45.31, 43.75, 45.31, 54.69], [12.50, 12.50, 14.06, 21.88], [6.25, 10.94, 12.50, 12.50]]
  }
};
let selectedBenchmark = 'mypc';
let selectedMetric = 'score';

function renderResults(announce = true) {
  const benchmark = benchmarks[selectedBenchmark];
  const metricName = selectedMetric === 'score' ? 'Mean evaluation score' : 'Full-credit success rate';
  const suffix = selectedMetric === 'sr' ? '%' : '';
  const unit = selectedMetric === 'score' ? 'points' : 'pp';
  const data = benchmark[selectedMetric];
  document.getElementById('chart-title').textContent = `${benchmark.title} · ${metricName}`;
  document.getElementById('chart-unit').textContent = selectedMetric === 'sr' ? '0–100% · higher is better' : '0–100 · higher is better';
  document.getElementById('results-context').textContent = benchmark.description;
  document.getElementById('table-caption').textContent = `${benchmark.title} · ${metricName} (${selectedMetric === 'sr' ? '%' : '0–100'})`;
  document.querySelectorAll('[data-benchmark]').forEach(button => {
    const active = button.dataset.benchmark === selectedBenchmark;
    button.classList.toggle('selected', active); button.setAttribute('aria-pressed', String(active));
  });
  const modelCharts = data.map((values, index) => {
    const model = document.createElement('div'); model.className = 'chart-model';
    const area = document.createElement('div'); area.className = 'bar-area'; area.setAttribute('aria-hidden', 'true');
    values.forEach((value, method) => {
      const column = document.createElement('div'); column.className = 'bar-column';
      const bar = document.createElement('div'); bar.className = `bar ${colors[method]}`; bar.style.height = `${value}%`;
      bar.title = `${modelNames[index]} · ${methods[method]}: ${value.toFixed(2)}${suffix}`;
      const label = document.createElement('span'); label.textContent = value.toFixed(1);
      bar.append(label); column.append(bar); area.append(column);
    });
    const label = document.createElement('div'); label.className = 'model-label'; label.textContent = modelNames[index];
    const gain = document.createElement('div'); gain.className = 'gain-label'; gain.textContent = `+${(values[3] - values[0]).toFixed(2)} ${unit} vs. No Skill`;
    model.append(area, label, gain); return model;
  });
  document.getElementById('results-chart').replaceChildren(...modelCharts);
  const rows = data.map((values, index) => {
    const row = document.createElement('tr'); const title = document.createElement('th'); title.scope = 'row'; title.textContent = modelNames[index]; row.append(title);
    const best = Math.max(...values);
    values.forEach(value => { const cell = document.createElement('td'); cell.textContent = value.toFixed(2) + suffix; if (value === best) cell.className = 'best'; row.append(cell); });
    const gain = document.createElement('td'); gain.className = 'gain-cell'; gain.textContent = `+${(values[3] - values[0]).toFixed(2)} ${unit}`; row.append(gain); return row;
  });
  document.querySelector('#results-table tbody').replaceChildren(...rows);
  if (announce) document.getElementById('results-announcement').textContent = `Showing ${metricName.toLowerCase()} for ${benchmark.title}.`;
}
document.querySelectorAll('[data-benchmark]').forEach(button => button.addEventListener('click', () => { selectedBenchmark = button.dataset.benchmark; renderResults(); }));
document.getElementById('metric').addEventListener('change', event => { selectedMetric = event.target.value; renderResults(); });
renderResults(false);

const figureDialog = document.getElementById('figure-dialog');
document.getElementById('open-figure').addEventListener('click', () => figureDialog.showModal());
document.getElementById('close-figure').addEventListener('click', () => figureDialog.close());
figureDialog.addEventListener('click', event => { if (event.target === figureDialog) { const rect = figureDialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) figureDialog.close(); } });

document.getElementById('copy-citation').addEventListener('click', async () => {
  const button = document.getElementById('copy-citation'); const label = button.querySelector('span');
  const citation = document.getElementById('bibtex').textContent;
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
    await navigator.clipboard.writeText(citation);
    label.textContent = 'Copied!'; document.getElementById('copy-status').textContent = 'BibTeX copied to clipboard.';
    setTimeout(() => { label.textContent = 'Copy BibTeX'; }, 2200);
  } catch {
    const range = document.createRange(); range.selectNodeContents(document.getElementById('bibtex'));
    const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    label.textContent = 'Text selected';
    document.getElementById('copy-status').textContent = 'Clipboard access is unavailable. Citation text selected; use your system copy shortcut.';
    setTimeout(() => { label.textContent = 'Copy BibTeX'; }, 3000);
  }
});

if ('IntersectionObserver' in window) {
  const links = [...document.querySelectorAll('nav a')];
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) links.forEach(link => link.classList.toggle('active', link.hash === `#${entry.target.id}`));
    });
  }, { rootMargin: '-20% 0px -65% 0px', threshold: 0 });
  links.forEach(link => { const section = document.querySelector(link.hash); if (section) observer.observe(section); });
}
