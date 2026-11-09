# Clean install on Windows (Task 23, 2026-11-09)

Windows 11, Intel Iris Xe laptop, Python 3.13.2, Node 22.14, ffmpeg 8.1 full, Edge. Claude Code 2.1.80. The macOS half is out
of scope (ruling G2). A shared PC: other sessions were running while this test ran, so times are not best case.

## Setup of the test

- Project folder with a space and an accent: `%TEMP%\floored install test\Área de Trabalho\meu reel`.
- Fresh `FLOORED_HOME` next to it (`%TEMP%\floored install test\home`), never the real `~/.floored`.
- `FLOORED_RVM_MODEL` pointed into that home so the model download really ran (the default `~/.cache/rvm/` already holds
  the file and was left alone).
- Studio on port 51030 (`FT_PORT_BASE`).
- No `claude` chat session was started (the "Claude follows the skill" part is covered by Task 20). The real `claude plugin`
  commands ran, then the exact commands SKILL.md prescribes, in its order, using the **installed copy** of `floored.py`
  (`~/.claude/plugins/cache/floored/floored/0.1.0/skills/floored/app/`), which `diff -r` showed identical to the repo.

## Steps, times, sizes

| # | Step | Result | Time | Size |
|---|---|---|---|---|
| 1 | `claude plugin marketplace add <repo> --scope project` | added, "declared in project settings" | 0.4 s | none |
| 2 | `claude plugin install floored@floored --scope project` | installed; `plugin list` shows `floored@floored` 0.1.0, scope project, enabled | 0.6 s | 11.6 MB copied into the plugin cache (67 files) |
| 3 | `doctor --json` (first) | `ok: false`; python, ffmpeg, node, browser found; venv, packages, rvm-model, renderer missing | 3.8 s | states `downloadMb` 463 |
| 4 | `doctor --install venv` | ok | 15 s | 12 MB stated, 92 MB on disk |
| 5 | `doctor --install packages` | ok (numpy, onnxruntime-directml 1.23.0, ...) | 72 s | 37 MB stated; pip reused some cached wheels |
| 6 | `doctor --install rvm-model` | ok, progress "9 of 15 MB", "13 of 15 MB" | 12 s | 15 MB |
| 7 | `doctor --install renderer` (hyperframes 0.9.22 through npm, plus its test video) | ok | 743 s (12 min 23 s) | 117 MB on disk, 77 packages; browser not downloaded (see concern 2) |
| 8 | `doctor --install words` (speech reader, model into the home) | ok | 44 s | 142 MB model on disk |
| 9 | `doctor --json` (second) | exit 0, `ok: true`, `downloadMb` 0, "Everything floored needs is installed." | n/a | n/a |
| 10 | `serve --workspace <project> --detach` | `FLOORED_URL=http://127.0.0.1:51030/`, HTTP 200 | 1.5 s | none |
| 11 | `add` the sample `source.mp4` (1080x1920, 24 fps, 5.04 s, 5.4 Mbps, copied into the project) | take `261109-172644-b116` | instant | none |
| 12 | `wait --take` | exit 0: cutting, measuring, shadow, words (speech found, English) | 507 s (8 min 27 s) | none |
| 13 | Export of the Original look through the studio's real Export, then Render (Playwright, Edge) | "Your intro is ready" | 148 s | 6.5 MB mp4 |
| 14 | `dev/bench/export_table.py` on the export | 1 of 1 rows pass | n/a | n/a |
| 15 | `stop` | server stopped, port 51030 closed | n/a | n/a |

Doctor summary line (first run, before any download):

> Setup needs 4 downloads, about 463 MB in total: the Python environment (12 MB), the Python add-ons (37 MB), the cutout model
> (15 MB), the video maker (399 MB). Optional, not counted: the speech reader (208 MB).

Export table row: 1080x1920, 24 fps, 121 frames (same as the take), video 10.04 Mbps (need 8.00, min 7.84), -14.0 LUFS,
true peak -1.7 dBTP, AAC 48 kHz: PASS.

Totals (required items plus the speech reader):

- Setup time, the five `--install` steps: 886 s = **14.8 minutes** (12.4 of them the renderer). Plus 8.5 minutes to cut the sample.
- Stated download: **463 MB** required, **671 MB** with the speech reader.
- On disk in the fresh home: venv 409 MB, renderer 117 MB, speech model 142 MB, cutout model 15 MB = **683 MB**.
  Over the wire it was less, because pip reused cached wheels and the browser was not downloaded. What was surely fetched:
  cutout model 15 MB, speech model about 142 MB, npm packages (at most 117 MB); pip wheels were not metered.

## Pass / fail (design 15.1)

| Criterion | Result | Evidence |
|---|---|---|
| Only consent-type prompts; no CLI step asked anything unexpected | PASS | none of the steps prompted; every install is an explicit `--install ITEM` |
| Total download stated before the first download | PASS | step 3 printed 463 MB (and the optional 208 MB) before steps 4 to 8 |
| Studio opens | PASS | HTTP 200 on the URL; Playwright page load (Edge) with 0 page errors, 0 console errors, empty `window.__ft.log`; ready in 1.8 s |
| The sample exports and passes the table | PASS | steps 13 and 14 |
| Works with a space and an accent in the path, from the installed copy | PASS | workspace written correctly in `.server.json` |
| Clean-up leaves the maintainer's user config as it was | PASS | see Clean-up |

## Surprises and concerns

1. **The renderer install took 12 min 23 s** ("added 77 packages in 12m"), 84 percent of the setup. The doctor states the
   size but gives no time, so the creator faces a long silent step. Worth a "this one takes about 10 minutes" hint in the setup
   question. Unclear whether it is npm on this PC (antivirus, shared load) or typical.
2. **The browser download was not exercised.** `renderer` found `chrome-headless-shell` in the shared HyperFrames cache
   (`~/.cache/hyperframes/chrome`, from an earlier project), so the 399 MB figure (which includes the browser) could not be
   confirmed: the npm side was 117 MB. The step also touched that shared cache's `history/` and `locks/` folders (HyperFrames'
   own bookkeeping, outside `FLOORED_HOME`).
3. **`claude plugin marketplace add --scope project` also registers the marketplace in the user-level
   `known_marketplaces.json`.** While the test ran, `claude plugin marketplace list` showed `floored` from every folder.
   `marketplace remove` took it out again.
4. For a directory marketplace, `claude plugin list` (PowerShell) shows "Read from: <repo>\plugin" beside the cache copy
   (`installPath`). The two were identical here; a creator installing from a real repo has only the cache copy.
5. From Git Bash the accented project path looked mangled when read raw through Python in `installed_plugins.json`
   (`projectPath`). Both shells still resolved the project plugin and PowerShell's `plugin list --json` showed the path correctly.
   Looks like a Claude Code detail, not ours.
6. `requirements.txt` installs `onnxruntime-directml` on Windows (by design). The optional graphics-card check
   (`doctor --gpu-check`) was not accepted and not run.
7. The cut took 8 min 27 s for a 5 s 1080p take (inside the 10 minute target) on a shared PC with Iris Xe.
8. The "Claude asks one question and the creator says yes" part was not run here (no `claude` chat, by the controller's note);
   it stays covered by Task 20.

## Clean-up

- `claude plugin uninstall floored --scope project` and `claude plugin marketplace remove floored`, run from the test
  project: both succeeded; the project `.claude/settings.json` ended with empty `enabledPlugins` and `extraKnownMarketplaces`.
- Removed `~/.claude/plugins/cache/floored` (left behind by the uninstall) and the whole `%TEMP%\floored install test`
  folder (project, exports, fresh home with venv, renderer and models).
- Studio stopped with `floored stop`; port 51030 closed; no Python or Node process left with the test folder in its command line.
- The user-scope lists compared with what was recorded before step 1: `claude plugin list`, `known_marketplaces.json` and
  `installed_plugins.json` all held the same entries as before (nothing of floored left in them). The CLI's display of the
  marketplace list differed between shells (from PowerShell it adds a built-in directory row and `@main` on one URL); the
  files themselves are unchanged.
  `~/.cache/rvm/` and the real `~/.floored` were not touched.
