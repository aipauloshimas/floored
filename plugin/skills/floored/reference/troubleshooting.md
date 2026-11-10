# Troubleshooting

`APP` and `WS` are as in SKILL.md. Messages are quoted as the app prints them. "The creator sees" is where they show up.
Say it in the creator's language and plain words. When a step keeps failing after one retry, show the message and the
log: `WS/floored/server.log` (the server), `WS/floored/takes/<id>/log.txt` (one take's cutout and checks),
`WS/floored/exports/<id>/export.log` (one export), or the message in the studio.

## Exit codes

| Command | Exit | Meaning | Claude does |
|---|---|---|---|
| any except `doctor` | 5 | "floored isn't set up yet. Ask Claude to run the setup." | Run the setup flow (SKILL.md step 1 to 2). |
| `doctor` | 0 / 1 | 0: nothing required is missing. 1: something is. | Read the report; ask once; install. |
| `doctor --install` | 0 / 1 / 2 | 1: that step failed (see Setup). 2: no such step, or a program installed by its own command. | Show the message; for 2 on a program, run the `command` it prints (after consent). |
| `serve` | 1 | The studio didn't start, or one is running but silent. | See Studio. |
| `add` | 2 | The clip is not usable, or the studio refused it. | See Adding a clip. |
| `add`, `suggest`, `retry` | 1 | The studio couldn't be reached. | See Studio. |
| `wait` | 0 / 2 / 3 / 4 | 0 ready. 2 no such take. 3 failed. 4 timed out. | 3: Processing errors. 4: `wait` again, the take is still being cut. |
| `doctor --gpu-check` | 1 | The check couldn't run: the cutout model or the Python add-ons are missing. | Install those first (see Setup), then check again. |
| `suggest` | 2 | The JSON is invalid, or no such take. | Fix the JSON by the message; see hooks.md. |
| `retry` | 2 | The take can't be retried. | See Retrying. |
| `stop`, `status` | 1 | The server is busy, or can't be stopped. | Wait a minute and try again; never kill it by name. |

## Setup

| Message or sign | The creator sees | Claude does |
|---|---|---|
| "Python 3.10 or newer isn't installed." / "Your Python is X, and floored needs 3.10 or newer." | In the setup question | Offer the report's `command` (winget or brew; else the download page). After it runs, `doctor --json` again; it finds the new program even if this shell's PATH is stale. Try `py -3` on Windows. |
| "ffmpeg isn't installed." / "This ffmpeg is missing parts floored needs (...). Install the full build." / "ffprobe (it comes with ffmpeg) wasn't found. Reinstall ffmpeg." | In the setup question | Offer the full build by the report's `command`. A partial build (no HDR, cutout-video or final-video encoder) is not enough. |
| Node.js missing or older than 22 ("Node.js 22 or newer is needed first. Run the install command from the doctor report.") | In the setup question | Offer the report's `command`; install it before `renderer`. |
| "Neither Chrome nor Edge was found. The studio opens in one of them." | In the setup question | Offer Chrome; Brave and Arc also work if the creator opens the address themselves. |
| "The saved location of X was gone, so floored looked again." | A note in the report | Nothing. |
| "Python 3.10 or newer is needed first. Run the install command from the doctor report." | After a `venv` install | Install Python first. |
| "The Python environment wasn't created." | After a `venv` install | Run it once more; then show the message. |
| "python environment failed (exit N): ..." / "python add-ons failed ..." / "speech reader failed ..." | After a `packages` or `words` install | Usually the internet connection or disk space. Check both, run the step again. Show the last line if it repeats. |
| "The Python add-ons installed but don't start. Run the setup again." / "The Python add-ons stopped working after the speech reader was added. Run the setup again." | After `packages` or `words` | Run `--install packages` again. |
| "Install the Python add-ons first, then run this step again." | After a `renderer` install | Install `packages` first. |
| "A different file is already at <path>. floored won't overwrite it: move it away, then run the setup again." | After an `rvm-model` install | Tell them the path; they move or rename that file; run the step again. Never delete it for them. |
| "Couldn't download the cutout model (...). Check the internet connection and try again." | After an `rvm-model` install | Check the connection; run it again. |
| "The cutout model didn't download correctly (the file isn't the expected one), so it was thrown away. Try again." | After an `rvm-model` install | Run it again; if it repeats, the network is altering the file (a proxy): try another network. |
| "Another file appeared at <path> while downloading, so it was left alone." | After an `rvm-model` install | Run the step again. |
| "The video maker didn't install correctly." / "The video maker ran but didn't make its test video." / "video maker failed (exit N): ..." | After a `renderer` install | Needs internet and about 400 MB free. Run the step again; show the last line if it repeats. |
| "The speech reader didn't install correctly." | After a `words` install | Run it again. It is optional: the creator can type the words instead. |
| "The cutout model is needed first." / "Install the Python add-ons first, then check again." | After `doctor --gpu-check` | Install that item, then check again. |
| "Cutouts will use the processor (...)" | After `doctor --gpu-check` | Not an error. Say cutouts use the processor, and carry on. |
| "There is no setup step called X." | After a bad `--install` | Use `venv`, `packages`, `rvm-model`, `renderer` or `words`. |

## Studio

| Message or sign | The creator sees | Claude does |
|---|---|---|
| "floored: a server for this project is running (pid N) but didn't answer. It may be busy with a cutout or a render. Wait a minute and try again; nothing was changed." (`serve`, `add`, `suggest`, `retry`) | Nothing, or a slow page | Wait a minute and run it again. If it still refuses and no cutout or export is running, it is a pid that another program reused: run `APP stop --workspace WS`, then delete `WS/floored/.server.json` if it is still there, then `serve` again. |
| "floored: couldn't reach the server (pid N). It may be busy with a cutout or a render, so it was left running. Try again in a minute." (`stop`) | Nothing | Wait; try again. |
| "floored: couldn't stop the server (pid N)." | Nothing | Try once more; if it persists tell the creator, don't kill by name. |
| "floored: the server didn't start (...). Details: <log>" | No studio | Read the log's last lines. A port clash needs nothing (it picks the next free one). Show the cause if it repeats. |
| `NO_CHROMIUM https://www.google.com/chrome/` | The studio didn't open | Give them the address and the Chrome link. |
| "floored: couldn't open the browser (...). Open <url> yourself." | The studio didn't open | Give them the address. |
| `status` shows `"url": null` | The page can't connect | The studio stopped (it exits after two idle hours). Run `serve --detach` again; the takes are kept. |
| "This server only answers on 127.0.0.1." / "Requests from other sites are not allowed." (403) | A blank page or an error | The address must be exactly the one `serve` printed, opened in the creator's own browser. |

## Adding a clip

| Message | The creator sees | Claude does |
|---|---|---|
| "floored: can't find the video: <path>" | Nothing | Ask for the right path; Windows paths need quotes. |
| "Please add a video file (MP4, MOV, M4V, WebM, MKV or AVI): <path>" / "Please drop a video file (MP4, MOV, M4V, WebM, MKV or AVI)." (the studio) | Nothing, or the studio says it | Ask for a video file. |
| "that file is empty: <path>" / "That file is empty." | Nothing | Ask for another copy. |
| "that file is too large (2 GB at most): <path>" / "That file is too large (2 GB at most)." | Nothing | Ask them to trim or compress it. |
| "This clip is X seconds long. Trim it to 10 seconds or less and add it again." | Same, in the studio | Ask them to trim; 3 to 8 s works best. |
| "We couldn't open this video. Try exporting it again as an MP4 or MOV." | Same, in the studio | Ask for an MP4 or MOV export of the clip. |
| "We couldn't find a video in this file. Add an MP4 or MOV with a picture." | Same, in the studio | Same; the file may be audio only. |
| "That file doesn't look like a video we can read. Try an MP4 or MOV." | Same, in the studio | Same. |
| "We couldn't check this video in time. Try exporting it again as an MP4 or MOV." | Same, in the studio | Same. |
| "The upload was interrupted. Try again." / "floored: couldn't send the video to the studio (...)." | Nothing | Run `add` again. |

## Processing errors (`wait` exit 3, and the studio's red message)

`wait` prints `{"take", "stage": "error", "message"}`. Retry once with `APP retry --workspace WS --take ID`, then
`wait --take ID` again. If it fails a second time with the same message, show it and stop retrying.

| Message | Claude does |
|---|---|
| "The cutout stopped before the end. Try again, and if it keeps happening, ask Claude for help." | Retry. Check that the computer isn't asleep or out of disk space. |
| "The cutout tool isn't set up yet. Ask Claude to finish the floored setup, then try again." | Run the setup flow for `rvm-model` and `packages`, then retry. |
| "We couldn't find a person in this clip. Make sure you are in the frame, from head to toe, then add it again." | Show [filming](filming.md); they film again. Retrying won't help. |
| "We couldn't draw your shadow." / "We couldn't make the preview of your cutout." / "We couldn't read the cut-out video." / "We couldn't make the preview (...)." / "We couldn't convert this clip. Try exporting it again as an MP4." | Retry once. If it repeats, ask for an MP4 re-export of the clip. |
| "Something went wrong while processing this clip. Try again, and if it keeps happening, ask Claude for help." | Retry once. If it repeats, read `WS/floored/server.log` and tell the creator what you find. |
| "The server restarted before this clip was finished. Drop it in again." | Retry. If it can't, `add` the clip again. |
| "The uploaded file is missing. Drop the clip in again." | `add` the clip again. |

## Retrying (`retry` exit 2)

| Message | Claude does |
|---|---|
| "No such take." / "floored: no such take: ID" | Check the id (`status` lists takes). |
| "This take has not failed (it is <stage>)." | Nothing to retry: `wait` for it. |
| "This take is already queued." | `wait` for it. |
| "The uploaded file is gone. Add the clip again." | `add` the clip again. |
| A refusal ("This clip is X seconds long...") | The clip itself is the problem: ask for a trimmed one. |

## Take warnings (the `warnings` list in the ready result)

Warnings don't stop the take. Explain the ones that matter, with the fix for next time, using [filming](filming.md).

| Code | The creator sees | Claude does |
|---|---|---|
| `short` | "This clip is only X s long. Film at least 3 seconds so there is time for the words." | Fine to continue; offer a longer take. |
| `long` | "This clip is X s long. About 8 seconds or less works best..." (over 10 s: "just over 10 seconds") | Continue; longer takes cost more waiting. |
| `landscape` | "This video is wide, not tall. Hold your phone upright and film again." | Recommend filming again. |
| `lowres` | "This video has a low resolution, so it may look soft..." | Continue; suggest 1080p or better. |
| `aspect` | "This video isn't the usual tall phone shape (9:16), so the sides may be cropped..." | Continue or film again. |
| `hdr` | "This is HDR video. We turn it into standard colors..." | Continue; colours may differ from the phone. |
| `edge` | "Part of you touches the edge of the frame at <times>..." | Recommend stepping back or zooming out. |
| `legs` | "We couldn't find your legs and feet, so the words may cover them. Film from a little further back and less straight down, so your legs show." | Recommend filming again at the guide's angle (about 45–50°, not straight down). |
| `moved` | "Your feet move during the clip, so the words may not stay lined up with you..." | Recommend standing still. |
| `people` | "It looks like there is more than one person in the frame..." | Recommend a take with only them. |
| `noperson` | "We couldn't see a person in this clip. Make sure you are in the frame, from head to toe." | Recommend filming again. |

## Export problems (the creator presses Export; Claude only explains)

The creator sees the message in the Export dialog. Never render or fix it from Bash. Tell them what it means and to
press Export again, or to press it again after the setup step. `retry` is for takes: it does nothing for an export.

- **The same message twice:** don't ask for a third try. Read `WS/floored/exports/<id>/export.log` (the newest folder
  in `WS/floored/exports/`) and tell them in plain words what stopped it. When it is nothing they can change (a failed
  check, an error in the app), it is a bug in the app: say so, and offer the update as a maybe (Updating, below). You
  don't know that a fix is out, so never promise one.
- **A video left in that folder:** when the check stopped the export, the folder holds `<take name> - floored.mp4`, the
  picture with its sound, which is the file the check measured. It is theirs, but it is not the finished export: the
  check stopped it for a reason. Say where it is and exactly what the log says is wrong with it, then let them decide.
  Never call it finished, and never repair it from Bash. `render.mp4` and `video.mp4` are earlier steps with no sound:
  never hand those over as the video.

| Message | Claude does |
|---|---|
| "The video maker isn't installed yet. Ask Claude to finish the setup." / "The export engine isn't built yet (missing ...)." | Run `doctor --install renderer` (after consent), then they press Export again. |
| "This take isn't ready yet." / "This take is missing X. Drop the clip in again." / "This take has not been measured yet." | `wait` for the take, or `add` the clip again. |
| "The export didn't come out at your take's quality, so we stopped. Try again, and if it keeps happening, ask Claude for help." | They press Export again. If it repeats, read `WS/floored/exports/<id>/export.log` (the line `CHECK FAILED` has the numbers; the export is the newest folder in `WS/floored/exports/`) and tell them what you find, in plain words (`loudness` is how loud the sound came out: -15.7 LUFS is quieter than -14). A line that starts `note:` about the video bitrate is information: it never stops an export. |
| "The video couldn't be encoded: ..." (the text after the colon is the last lines of the encoder's output) | The render finished but the second step, the final encode, stopped. Check disk space and that the computer isn't asleep, then they press Export again. If it repeats, read the end of `WS/floored/exports/<id>/export.log`; the intermediate render stays in that folder (`render.mp4`). |
| "Something went wrong while exporting (...)." (the brackets hold an error type and text, e.g. `FileNotFoundError: ...`) | A bug or a missing program, not the creator's doing. Read `WS/floored/exports/<id>/export.log` (the traceback is at the end) and tell them what you find. If the text names ffmpeg or a missing file, run `doctor` and fix what it reports, then they press Export again. A take's own details are in `WS/floored/takes/<id>/log.txt`. |
| "The video took too long to process, so we stopped. Try again, and if it keeps happening, ask Claude for help." | A step of the export hung (its command and the seconds are in `export.log`). They press Export again; check that the computer isn't asleep or short of disk space. |
| "The video tools aren't installed yet. Ask Claude to finish the setup." | Run `doctor`, install what it lists (ffmpeg), then they press Export again. |
| "The render didn't finish: ..." / "The video couldn't be finished." / "The sound couldn't be mixed." / "The finished video could not be read (...)." / "The rendered video could not be read (...)." / "The encoded video could not be read (...)." | They press Export again; check disk space and that the computer isn't asleep. If it repeats, read `export.log` in that export's folder. |
| "Unknown font ..." / "The font file ... is missing" | Reinstall the plugin; the fonts ship with it. |

## Updating

floored doesn't update by itself. When the creator reports a bug, or the app doesn't do what this skill says, the fix
may already be out. Offer the update, and on a yes run:

```
claude plugin marketplace update floored
claude plugin update floored@floored
```

Then they start a new Claude Code session: the one that is open keeps the old skill. A studio that is still open
keeps the old app too, so run `APP stop --workspace WS` first (the takes are kept). The installed version is the
`version` in `<skill folder>/../../.claude-plugin/plugin.json`; the newest one is in the same file of the repository.
