---
name: floored
description: Use when a creator wants a "floor text" intro, or "floored" (3D text on the floor around them, "words on the floor around me"), made from their own top-down clip, in English or Portuguese ("texto 3D no chão", "intro com texto no chão", "faz uma intro com texto no chão"), or drops a tall top-down clip of themselves and asks for an intro. Not for captions or subtitles, editing a whole reel, or videos that aren't 9:16.
---

# floored.

*your words, on the floor, in 3D.* In prose the product is "floored" (lowercase); "floored." with the period is the
wordmark, for display only. floored turns a creator's top-down take into an intro: they stand on a floor of big 3D
words. It is a local app
(a studio in the browser) that Claude sets up, starts, feeds and helps. Everything runs on the creator's computer; the
video never leaves it. After setup it works offline.

**Claude's part:** set up, start the studio, send the take in, write the hook suggestions, explain problems.
**The creator's part:** pick the look and press **Export**. Claude never does that for them.

## Run the app

This skill's folder is given when the skill loads (its base folder). Every command is:

```
python "<skill folder>/app/floored.py" <command> ...
```

On Windows use `py -3` when `python` is missing or older than 3.10. If neither starts, or only the Windows Store stub
answers (it opens the Store instead of printing a version), the doctor cannot run: make Python the first item of the
setup question in step 2 (`winget install --id Python.Python.3.12 -e` on Windows, `brew install python@3.12` on a Mac,
about 27 MB), run it on a yes, then start again from step 1. Below, `APP` means that command prefix and `WS`
means the creator's current project folder (the working directory); takes and exports go in `WS/floored/`.
`floored.py` hands over to its own private Python environment by itself. Run `APP <command> --help` for any flag.

## The flow

1. **Setup check.** `APP doctor --json`. Exit 0 and `"ok": true`: skip to step 3. Otherwise go to step 2.
2. **Setup, with consent.** Ask **one** question that lists every item with `ok: false`, with its size (`mb`, plus
   `downloadMb` for the total) in plain words: "the cutout model (15 MB)", never the internal ids. Say that the video
   maker (`renderer`) is the long step and quote its `minutes` field: "the video maker (399 MB, about 12 minutes)", often
   10 to 15. The speech reader carries `minutes` too (about 1). Items with
   `how: "manual"` (Python, ffmpeg, Node.js, Chrome or Edge) are installed by the `command` in the report, and the
   question says so. List the optional ones apart: "the speech reader" (`words`, reads the words from the creator's
   speech; without it they type the words) and the graphics-card check (`doctor --gpu-check`, no download, about a
   minute). On a yes, first run the manual commands (Python, Node.js, ffmpeg, browser: `venv` needs Python and `renderer`
   needs Node.js), then `APP doctor --json` again. Then run `APP doctor --install ITEM` for each accepted `auto` item in
   this order: `venv`, `packages`, `rvm-model`, then `doctor --gpu-check` if they chose it, `renderer`, `words`; run
   `APP doctor --json` once more. Install only what they accepted. **Run every `doctor --install` in the background**
   (Bash `run_in_background`; `renderer` above all: the foreground tool stops at 10 minutes and the step takes longer
   than that on a slow PC) and wait for it to exit before starting the next one; never start a second install of the
   same item while one runs. While one runs, tell the creator it is still working (for the video maker: it prints almost
   nothing until it is done, so a quiet screen is normal). A failed step: [troubleshooting](reference/troubleshooting.md).
3. **No clip yet?** Show them [how to film it](reference/filming.md) in your own words (phone up high and a little
   in front, tilted down, not straight down, whole body, one spot, 3 to 8 s), then start the studio (step 4, no
   `add`). Its home page has a sample take: point at **Try the sample take**, so they can try the looks now and film
   later. Never offer to generate the take or to make it for them: it is theirs to film.
4. **Start the studio.** `APP serve --workspace WS --detach` prints `FLOORED_URL=<url>`. Open that URL in the desktop
   app's Browser pane when your tools have one; otherwise run the same command with `--open` (Chrome or Edge). If it
   prints `NO_CHROMIUM`, give them the address and say it needs Chrome, Edge, Brave or Arc. With no clip path, start `APP wait --workspace WS --next` in the
   background right after `serve`, before the creator drops the clip in the page: `--next` only catches takes created
   after it starts.
5. **With a clip path:** `APP add --workspace WS "<path>"` prints `{"take", "url"}` and processing starts at once; open
   that `url`. **Without a path:** the creator drops the clip in the studio; the `--next` waiter from step 4 is already running.
6. **Wait, in the background.** `APP wait --workspace WS --take ID` (or `--next` for a clip dropped in the page), run
   in the background so the creator can use the studio meanwhile. Tell them the studio shows the time left. Quote that
   figure, never your own guess (see [Wait time](#wait-time)). Exit 0: ready, step 7. Exit 3: failed. Exit 4: timed
   out, wait again. Both: [troubleshooting](reference/troubleshooting.md).
7. **Hooks.** The ready result has `hasWords`, `language`, `transcript` and `warnings`. Write 4 hooks plus 1 small line
   by the rules in [hooks](reference/hooks.md), then `APP suggest --workspace WS --take ID --file <path>`. On Windows
   write the JSON to a UTF-8 file and pass that path (a PowerShell pipe can mangle accents); `--file -` reads stdin, fine
   in Git Bash or with a heredoc. Tell them the suggestions are in the studio's Suggestions tab. No speech (`hasWords` false, or a junk
   transcript): ask one question about the reel, then write the hooks from the answer.
8. **Stay available.** Explain each warning from the take in plain words (the `code` has a row in
   [troubleshooting](reference/troubleshooting.md)), re-run a failed step with `APP retry --workspace WS --take ID`,
   and point at the Export button when they are done designing.

## Wait time

The studio's processing screen shows "About N min left", and `wait` prints its progress. Quote that, once it appears.
Before it does, say only that cutting takes several minutes and a 4K take takes longer. Don't invent numbers, and
don't ask the creator for words, style or camera before the take is processing: the hooks come from their speech.

## Rules

- **Use this app.** When this skill applies, never compose the intro by hand with other video skills or HyperFrames.
- **Cutouts: the app's cutout model only.** Never `hyperframes remove-background`, u2net, rembg or keying.
- **Never press Export.** Never render from Bash, never "match the specs" by hand. The Export button is the creator's.
  "Just export it for me" gets a short reply: the look is theirs to confirm, press **Export** in the studio, and it
  already renders at their take's size and frame rate.
- **Never upload or send the video anywhere.** Nothing leaves the computer.
- **Never edit `take.json` by hand.** Hooks go in through `suggest`; everything else is the studio's.
- **Never install anything the creator didn't accept** in the one setup question.
- **Stop only what you started.** `APP stop --workspace WS` stops this project's studio; never kill processes by name.

| Excuse | Reality |
|---|---|
| "They asked me to export, that's the go" | The Export button belongs to the creator, always. Point at it. |
| "I'll check the take's specs and render with the CLI myself" | The app's export already matches the take. Never render from Bash. |
| "I'll ask for the words and style first" | Start processing first. The app suggests hooks from the speech. |
| "I'll hand-build it with the hyperframes skill, it's faster" | The app is the product. Use it. |
| "Setup is small, I'll just install it" | Ask once, with sizes. Then install. |
| "I'll tell them it takes about N minutes" | Quote the studio's estimate. |
| "They have no clip, so I'll offer to make one for them" | The take is theirs to film. Show the filming guide and point at the sample take. |

## Language

Talk to the creator in their language, in short friendly sentences with no jargon: "cutout model", "video maker",
never the names of the tools underneath. The studio itself is in English.
