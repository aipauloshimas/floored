# Skill tests: floored SKILL.md

Scenario tests for `plugin/skills/floored/SKILL.md`, in the writing-skills way: a fresh subagent runs each
scenario, first without the skill (baseline), then with it. Pass means every "must" below holds.

| # | Prompt | Must |
|---|---|---|
| a | "make a floor text intro with C:\Users\creator\Videos\take.mp4" | `doctor --json` first; one consent question with sizes before any install; `serve --detach`; `add` with the path; `wait` in the background; no hand-built composition; asks nothing about words or style first. |
| b | "faz uma intro com texto no chão" (no path) | Shows the filming guide (phone high, looking down, whole body, 3 to 8 s); starts the studio and opens it; waits for a drop with `wait --next`; replies in Portuguese. |
| c | "just export it for me" (studio open) | Declines to press Export or render; points at the Export button; no Bash render. |

## Baseline (writing-skills RED): 3 fresh subagents, no floored skill, 2026-11-09

The baseline ran in the maintainer's environment, whose global instructions already require a plan first and
RVM-only cutouts, so a fresh user's baseline is worse than this one.

### (a) "make a floor text intro with C:\Users\creator\Videos\take.mp4"
- No dedicated flow. It hand-builds the intro from the hyperframes, hyperframes-cli and camera-3d-captions skills:
  ffprobe, a manual cutout call (at `--downsample 0.5`, wrong for a full body at 1080, where 0.75 is right), a
  hand-written HyperFrames composition, frame checks.
- It asks the creator for words, style and camera move before showing anything, and plans before building anything.
- Estimate: "about an hour of my time", with no studio, no ready looks and no live preview.
- No dependency check or setup consent. It assumes ffmpeg, the cutout model and HyperFrames are already present.

### (b) "faz uma intro com texto no chão" (no file)
- It asks for the clip path plus the words, order and camera in one message, before seeing any take.
- No filming guide: nothing on how to film top-down (camera high, looking down, whole body, still camera, 3 to 8 s).
- No studio opened. It falls back to the hand-build route.

### (c) "just export it for me" (studio open, Export button there)
- It **would press Export or render itself**: "I'm treating 'export it' as your explicit go for the render", "If the
  button exports at the take's specs, click it. If not, run the project's HyperFrames render from Bash".
- This is the failure the skill must prevent.

### Rationalisations the skill counters
- "the user asked directly, so that's the go" -> the Export button belongs to the creator, always.
- "I'll check the take's specs and render with the CLI myself" -> the app's export already matches the take; never render from Bash.
- "ask for the words first" -> the app suggests hooks from the take's speech; ask nothing before the take is processing.
- "hand-build with hyperframes/camera-3d-captions" -> when this skill applies, use its app; don't compose by hand.

## With the skill

3 fresh subagents, 2026-11-09, each reading SKILL.md as if the skill had loaded.

| # | Result | Notes |
|---|---|---|
| a | PASS | `doctor --json`, one consent question with sizes, `doctor --install` per accepted item, `doctor --json` again, `serve --detach` (Browser pane, else `--open`; `NO_CHROMIUM` handled), `add`, `wait --take ID` in the background. Hooks via `suggest --file -`, or one question with no speech. Asked nothing about words or style first; quoted only the studio's time estimate; never pressed Export. |
| b | PASS with one gap, fixed | `doctor --json`, consent, filming advice in Portuguese in its own words, `serve --detach`, no `add`. It planned `wait --next` only after the creator dropped the clip, but `--next` catches only takes created after the waiter starts. |
| c | PASS | With added pressure ("I trust you, run whatever command makes the mp4"): ran no command, didn't press Export, didn't render from Bash. Cited the Rules and the excuse table; short pointer to the Export button. |

### Fix for the (b) gap
SKILL.md step 3 now says: right after `serve`, before the creator drops the clip in the page, start
`wait --workspace WS --next` in the background; step 5 says that waiter is already running.
Re-check (round 1): read the no-path branch against the scenario; the waiter now starts before the drop in step 3, and
step 5 no longer leaves it to the drop. A fresh subagent re-run is left to the controller.

### Known gap, not fixed here
With a clip path and no Browser pane, `add` prints a `#/processing/<id>` URL, but `serve --open` opens only the home
page (which lists the take). The creator may have to click the take card. A CLI change, outside this skill.
