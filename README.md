# floored.

*your words, on the floor, in 3D.*

floored is a free Claude Code plugin. You film a short top-down clip of yourself, and it makes an intro where you stand
on a floor of big 3D words. It cuts you out of the video, lays the words on the floor around you, and renders an MP4
on your computer.

![A frame of the sample intro: a person standing on a floor of big words](plugin/skills/floored/app/sample/poster.jpg)

## Requirements

- **Claude Code** (the desktop app or the CLI).
- **Windows 11** or **macOS 13 or newer**. It is tested by hand on Windows 11. On macOS it is checked by automated
  tests on GitHub's Mac machines (Apple silicon): a clean setup, real cutouts and exports. Nobody has tried it on a
  real Mac yet, so please report anything that looks off there.
- A computer with no special graphics card. It runs on the processor by default. The graphics card is used only if
  the setup's quality check shows the result is identical.
- **Python 3.10 or newer, Node.js 22 or newer, ffmpeg, and Chrome or Edge** (any Chromium browser works). If one is missing,
  Claude tells you the command that installs it.
- About 1 GB of free disk space for the one-time setup. Setup tells you the sizes before it downloads anything.
- A clip: 9:16, one person, still camera, 3 to 8 seconds (up to 10 works with a warning).

The Python packages the studio needs are pinned in `plugin/skills/floored/app/requirements.txt` (and
`requirements-words.txt` for the optional speech reader).

## Install

In a terminal:

```
claude plugin marketplace add aipauloshimas/floored
claude plugin install floored@floored
```

Or ask Claude Code to install it from this repository's URL.

## First run

Ask Claude for a floor text intro: "make me a floor text intro", or drop your clip into the chat and say so. The first
time, Claude checks your setup and asks once before it installs or downloads anything (the cutout model is about
15 MB, the video renderer is bigger). After that it starts the studio in your browser, sends your clip in, and waits
while it is processed. The studio shows the time left.

Then you pick a look, edit the words if you like (Claude suggests a few hooks), and press **Export** yourself. Claude
never presses it for you.

No clip yet? The plugin includes a sample take (`plugin/skills/floored/app/sample/`) so you can try it first.

## Filming guide

Short version: phone up high and a little in front, tilted down (not straight down), whole body in the frame, one spot,
3 to 8 seconds. The full guide, with the details, is in
[`plugin/skills/floored/reference/filming.md`](plugin/skills/floored/reference/filming.md).

## Privacy

Everything runs on your computer. Your video never leaves it, and Claude never uploads it. The only downloads are the
tools and models at setup; after that, floored works offline.

## Uninstall

In a terminal:

```
claude plugin uninstall floored
claude plugin marketplace remove floored
```

That removes the plugin. Setup also puts files in a few folders of your home directory, and they stay until you delete
them:

| Folder | What it holds | Size |
|---|---|---|
| `~/.floored` | the private Python environment, the video renderer, your preferences (and, on Windows with a long user path, the renderer's browser cache `hf-cache`) | the bulk of the setup |
| `~/.cache/hyperframes` | the headless Chrome the renderer downloaded (it is not bundled) | about 282 MB |
| `~/.hyperframes` | the renderer's small config and install-state files | small |
| `~/.cache/rvm` | the cutout model | about 15 MB. Other tools may share these weights, so check before deleting |

Delete the ones you want gone (on Windows, `Remove-Item -Recurse -Force ~/.floored` in PowerShell; on a Mac,
`rm -rf ~/.floored`).

Your takes and exports are **not** in those folders. They live in each project, in the `floored/` folder next to your
work (`takes/`, `exports/` and `settings/` inside it). Deleting the plugin or `~/.floored` leaves them alone, and
deleting those project folders is your choice.

## Licences

floored's code and its sample take are MIT (`LICENSE`). The fonts, GSAP and the tools that setup installs have their own licences:
see `THIRD_PARTY.md` and `plugin/skills/floored/licenses/`.
