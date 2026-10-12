# Work2Skill research project page

A responsive, dependency-free research website. The deployable files are at the root of this branch.

Live website: https://china-qijizhifeng.github.io/Work2Skill/

## Preview

```sh
python3 -m http.server 4173 --bind 127.0.0.1
```

## Content

- Paper: https://arxiv.org/abs/2610.12984
- Source repository: https://github.com/china-qijizhifeng/Work2Skill
- Dataset: https://huggingface.co/datasets/yuqi777/WorkDemo-350
- Results transcribed from Tables 2 and 3 of arXiv v1. `script.js` stores benchmark arrays; `index.html` includes a static fallback table.
- Framework figure reused from the public Work2Skill repository, with attribution on the page.
- The episode explorer mirrors the published `MyPCBench_final_video_64/cua_only-f001/` directory, including its six root entries, trace files, and 11 screenshot filenames (verified 2026-10-12).
- The small interactive spreadsheet is a schematic explanation, not a live model or a recorded demonstration.
- The dataset card's post hoc selection disclosure is retained alongside the reported OSWorld results. Source and dataset release scope are documented on the page.

## Hosting

GitHub Pages publishes the root of the `gh-pages` branch. No build step or package installation is required. Push changes to this branch to update the website; the research code remains on `main`.

Relative asset paths support hosting at `/Work2Skill/`. If the public domain changes, update the canonical URL and Open Graph URLs in `index.html`.

## Editing

`index.html` contains the three-part contribution overview and page content, `styles.css` the responsive visual design, and `script.js` the evidence explorer, results explorer, figure zoom, and clipboard interactions. Paper, code, and dataset links are grouped once in the hero.

## Visual identity

The supplied blue REC character is used unchanged for the navigation, hero, footer, favicon, and touch icon. The site palette follows its sky blue, cobalt, navy, and white tones, with red reserved for recording indicators. The original research figure is retained as published.
