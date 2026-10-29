# Third-party notices

## GitLab Handbook policy content

Policy Markdown in `data/gitlab_hr/` and policy excerpts in demonstration/evaluation artifacts originate from the public GitLab Handbook, copyright GitLab B.V. and its contributors. The Handbook identifies its content license as Creative Commons Attribution-ShareAlike 4.0 International:

- License statement: https://handbook.gitlab.com/handbook/about/handbook-usage/
- License: https://creativecommons.org/licenses/by-sa/4.0/
- Individual source URLs: `data/gitlab_hr/*/sources.json` and the attribution header of each Markdown file.

Changes include extracting policy body content, converting HTML to Markdown and resolving relative links. Demonstration answers are saved application outputs or reviewed public snapshots; they are not GitLab-authored policy text. Source excerpts remain identifiable and attributed under CC BY-SA 4.0. The project is not affiliated with or endorsed by GitLab.

## LightRAG

LightRAG is developed by HKUDS and contributors: https://github.com/HKUDS/LightRAG

DocTrace uses a pinned upstream container image. `deploy/build_hr_prelimit.py` extracts its source locally and generates a guarded integration hook for DocTrace's candidate-ranking policy. The hash-verified pinned `utils.py` diagnostic snapshot is retained under `evaluation/diagnostics/` solely for reproducible native selector replay; its MIT license and copyright are in `evaluation/diagnostics/LightRAG.LICENSE`. Other upstream container contents are not redistributed wholesale. The snapshot is unmodified; the offline runner executes a whitelist of original definitions and replaces only asynchronous executor scheduling.

## Browser libraries

Marked and DOMPurify are vendored for Markdown rendering and sanitization. Original license files and a hash manifest are preserved in both `app/web/vendor/` and the public demonstration's `docs/assets/vendor/`:

- Marked: `marked.LICENSE`.
- DOMPurify: `dompurify.LICENSE` and `dompurify.LICENSE-MPL`.

Other dependencies remain subject to the licenses distributed by their respective authors. Model names identify external services used in the local application; model weights are not included.
