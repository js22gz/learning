# learning

Static site for the merged learning project: the Kunskapsbank (a Swedish evidence library on learning) and the learning graph (a small set of claims that are deliberately attacked), in one place.

- Live: https://js22gz.github.io/learning/
- Build: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python build.py`
- Input: the project folder (set `LEARNING_ROOT`); output: `docs/`, served by GitHub Pages from `main:/docs`.

Two guiding questions: (1) What is optimal learning? (2) How do we achieve it when AI and screens are everywhere? No numeric confidence scores; claims carry a status, bounds and an attack record. Source notes are Swedish and shown verbatim. All source-to-claim links are a first-pass draft pending human review.
