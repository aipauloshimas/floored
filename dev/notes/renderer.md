# Renderer check and 4K method (Task 2)

HyperFrames 0.9.22, Windows 11, Node 22.14, ffmpeg 8.1, CPU box with an Intel Iris Xe (browser GPU auto-detected).
Everything below was produced by `dev/spike4k/run.py` against a clean profile (new `HOME`, `USERPROFILE`, `APPDATA`,
`LOCALAPPDATA`, `npm_config_cache`) in a temp folder outside the repo, with stdin closed. Composition: the 5.03 s sample
take export (121 frames, 1080x1920, 24 fps).

Gate ruling (2026-11-08): `crisp` is the variance of the Laplacian of the luma of the 4K crop over the same for the
lanczos 2x upscale of the 1080 crop, threshold 1.6; `geom >= 0.97` unchanged. The plan's mean-Sobel ratio could not pass
on this content and is kept only as the information column `sobel`.

## For Tasks 18 and 19

**(a) Account, login, plan: none.** The first render in an empty profile exited 0 with 121 frames, 1080x1920, 24 fps,
H.264, 11.4 Mbps (10M asked), and never prompted. Stdout had no login URL, no credits or plan message, no consent
question. Its extras: a "Keep editing by chatting with Framey in the HyperFrames desktop app" line (a download link), and
an "Agent feedback: hyperframes feedback --rating ..." line; stderr had a three-line telemetry notice ("anonymous until
you sign in ... Disable anytime: hyperframes telemetry disable"). `hyperframes auth login` exists but only for HeyGen
publishing and avatars; `render` never touches it. Stdin closed from the start (`subprocess.DEVNULL`), 15 minute timeout,
nothing hung.

**(b) Telemetry opt-out:** `HYPERFRAMES_NO_TELEMETRY=1` (or `DO_NOT_TRACK=1`; accepted values `1 true yes on`). Checked by
`run.py telemetry` (output in `logs/telemetry-status.txt`): with neither set `hyperframes telemetry status` prints
`Status: enabled, Source: config`; with either set it prints `Status: disabled` and the variable as the source. Also set
`HYPERFRAMES_NO_UPDATE_CHECK=1` (stops the version check and the auto-update). Task 18 should set all three on every
`hyperframes` call. Proof it matters: a node preload that logs non-loopback connections saw `us.i.posthog.com` (lookup and
connect, two processes) on a normal render, and nothing at all with the opt-out set.

**(c) Local install and the bin:**

```
npm install --prefix <dir> hyperframes@0.9.22          # 30 s, 110 MB in <dir>/node_modules, 72 MB npm cache
<dir>\node_modules\.bin\hyperframes.cmd                # Windows
<dir>/node_modules/.bin/hyperframes                    # macOS
```

Things Task 18 must handle:

- **Chrome is a separate download on first use** (`chrome-headless-shell` 152.0.7977.30, 282 MB, from
  `storage.googleapis.com/chrome-for-testing-public`, into `~/.cache/hyperframes/chrome`). The very first render pays for
  it (257 s wall versus 100 to 177 s of render time afterwards). "Works offline after setup" therefore needs a setup
  step: `hyperframes browser ensure` (also `browser path`, `browser clear`; `--force` re-downloads a partial one).
- **Keep the Chrome path short (Windows).** Observed: with the profile 8 folders deep in a session scratch folder, the
  render stopped after "file_server" with **exit 1 and no message at all**, and launching the cached
  `chrome-headless-shell.exe` by hand from that same path fails with `WinError 206 (filename too long)`. The path of that
  exe, which sits under the overridden `HOME`, was over the 260-character limit. The same job in
  a short temp folder such as `C:\Temp\fts4k` works, and an A/B with the real `HOME` works. Where the knob is (read from the
  package source, a fix **not tried**): the Chrome cache is `$HYPERFRAMES_CACHE_DIR/chrome` when that variable is set, else
  `~/.cache/hyperframes/chrome`; `HYPERFRAMES_BROWSER_PATH` (or `PRODUCER_HEADLESS_SHELL_PATH`) points at another Chrome or
  chrome-headless-shell binary. Not observed, only possible: a creator's own `C:\Users\<name>\.cache\...` is short, so a
  normal install should not hit this; a long project folder or a long folder for the renderer install were not tested and
  nothing says they matter (the failing path was Chrome's own exe). Cheap guard for Task 18: preflight the length of
  `hyperframes browser path` (under about 200 characters) and, if it is long, set `HYPERFRAMES_CACHE_DIR` to a short folder
  (after testing it), with a plain-language error instead of the silent exit.
- **First-run files** go under `~/.hyperframes/` (config, install-state) and `~/.cache/hyperframes/` (Chrome, history,
  locks); `render` takes a per-user lock (`--no-wait` fails at once instead of queueing).
- **Render time on this box** (the `rendered in` line of each log, 5.04 s of video): 1080 took 100 to 177 s, which is 20 to
  35 s of render per video second (median 25; the two slow ones are the first-ever render (177 s) and the proxy offline run (176 s); the
  others are 100 to 125 s). 4K took 268 to 390 s, 53 to 77 s per video second (flag 55, scale 53, zoom 77). HyperFrames lowers itself
  to 1 worker here ("Measured slow frame capture ... Reduced auto worker count"), and screenshot capture is forced by
  `mix-blend-mode` and by any DPR other than 1. Plan the honest estimate on 25 to 35 s per second of 1080 video, double for
  4K.

**(d) 4K method: `flag:--resolution portrait-4k`** (HyperFrames' own device-scale flag, composition unchanged, Chrome at
deviceScaleFactor 2), with `--video-bitrate 40M`. It passes the gate at all three instants:

| t | geom | crisp (Laplacian ratio) | sobel (info) |
|---|---|---|---|
| 1.0 | 0.9942 | 1.82 | 0.972 |
| 2.5 | 0.9954 | 2.25 | 0.867 |
| 4.6 | 0.9924 | 2.50 | 0.846 |

Worst `geom` 0.9924, worst `crisp` 1.82. The lead picked it as the first passing candidate in the plan's order, HyperFrames'
supported path, visually equal to `zoom` in the crops, and faster (291 s versus 403 s). Tested only with the person plate
upscaled to 4K (`person4k.webm`, see below); `flag` with the 1080 plate was not rendered.

## Offline

Same clean profile, opt-out set, 1080 render:

| Run | Exit | Frames | Outbound attempts seen |
|---|---|---|---|
| `HTTP_PROXY=HTTPS_PROXY=http://127.0.0.1:9` + opt-out | 0 | 121 | **not observed** (no preload; Node ignores `HTTP_PROXY`, so this run proves nothing by itself) |
| same, and every non-loopback connect/lookup of the node processes refused by a preload | 0 | 121 | none logged |
| telemetry on, connections only logged (contrast) | 0 | 121 | `us.i.posthog.com` |

Rows 2 and 3 carry the evidence: the preload sees the telemetry host when telemetry is on and sees nothing, with every
connection refused and the render still succeeding, when it is off. Limit: the proxy variables do not reach Chrome on
Windows and the preload only sees node processes, so Chrome's own traffic was not observed. The composition loads only
local files (fonts and GSAP are bundled), and the renders succeeded.

## 4K candidates

`person.webm` upscaled to 2160x3840 (lanczos, VP9 alpha yuva420p, CRF 18, 10.9 MB, 250 s) in every 4K candidate;
`shadow.webm` unchanged. 4K renders at `--video-bitrate 40M` (same bits per pixel as the 10M at 1080), all 121 frames,
24 fps, H.264, 42.4 Mbps measured. Frames 24, 60, 110 are t = 1.0, 2.5, 4.58 s (4.6 s is not on the 24 fps grid).

1. `flag`: `render --resolution portrait-4k`, composition untouched (Chrome at deviceScaleFactor 2).
2. `zoom`: root `data-width=2160 data-height=3840` and `.ft-root { zoom: 2 }`.
3. `scale`: root 2160x3840 holding a wrapper `.ft-root { transform: scale(2); transform-origin: 0 0 }`.

`geom` = SSIM (luma, gaussian 11x11) of the 4K frame lanczos-downscaled to 1080x1920 against the 1080 render.
`crisp` = variance of the 4-neighbour Laplacian of luma, 4K crop (x 200-1960, y 400-1800) over the same for the lanczos 2x
upscale of the 1080 crop (x 100-980, y 200-900). Pass needs `geom >= 0.97` and `crisp >= 1.6` at all three instants.
`sobel` is the old mean-Sobel ratio on the same crops (information only).

| Candidate | t | geom | crisp | sobel | geom (box downscale) | Pass |
|---|---|---|---|---|---|---|
| flag | 1.0 | 0.9942 | 1.817 | 0.972 | 0.9940 | PASS |
| flag | 2.5 | 0.9954 | 2.245 | 0.867 | 0.9958 | PASS |
| flag | 4.6 | 0.9924 | 2.497 | 0.846 | 0.9930 | PASS |
| zoom | 1.0 | 0.9876 | 4.740 | 0.974 | 0.9879 | PASS |
| zoom | 2.5 | 0.9882 | 5.961 | 0.871 | 0.9893 | PASS |
| zoom | 4.6 | 0.9874 | 5.376 | 0.849 | 0.9885 | PASS |
| scale | 1.0 | 0.9942 | 1.817 | 0.972 | 0.9939 | PASS |
| scale | 2.5 | 0.9955 | 2.240 | 0.867 | 0.9958 | PASS |
| scale | 4.6 | 0.9923 | 2.497 | 0.846 | 0.9929 | PASS |

All three pass; the first in the plan's order is `flag`. `geom` passes everywhere (worst 0.9874, zoom). `flag` and `scale`
are pixel-identical in practice (geom and crisp equal to three places); `zoom` re-lays the text out at 2x, which costs
0.005 of `geom` and is the slowest.

Wall time per render and file size: 1080 base 156 s / 7.2 MB; flag 291 s / 26.7 MB; scale 276 s / 26.7 MB; zoom
403 s / 26.8 MB (the first-ever render, with the Chrome download: 257 s).

### What `crisp` measures, and its limits

The first gate (mean Sobel) was unreachable here and the Laplacian ratio replaces it. Facts behind that, all from
`run.py measure` (information columns, same crops):

- **Mean Sobel is insensitive to edge width on this content.** The words are large flat red shapes, so the gradient lives
  in a few long edges, and the mean Sobel magnitude of an edge integrates to its contrast whatever its width. Blur sweep on
  the 4K crop itself (Gaussian sigma in 4K pixels), `crisp` / `sobel` against the same 1080 upscale, flag at t = 1.0 / 2.5 /
  4.6:

| 4K crop made softer or harder | crisp (Laplacian) | sobel (mean) |
|---|---|---|
| as rendered | 1.82 / 2.25 / 2.50 | 0.97 / 0.87 / 0.85 |
| blur 0.7 | 0.96 / 0.69 / 0.61 | 0.96 / 0.85 / 0.83 |
| blur 1.5 | 0.23 / 0.12 / 0.09 | 0.91 / 0.82 / 0.81 |
| blur 2.0 | 0.13 / 0.06 / 0.04 | 0.89 / 0.81 / 0.80 |
| unsharp mask (radius 1.5, 200 %) | 12.2 / 14.3 / 14.8 | 1.41 / 1.51 / 1.40 |

  Sobel moves by 0.08 at most between sharp and sigma 2; the Laplacian ratio falls by a factor of 14 to 60. Even sigma 0.7
  (a blur the eye barely sees at 4K) takes `flag` under 1.6. `zoom` shows the same pattern (blur 0.7: 1.58 / 1.06 / 0.83).
- **Ideal ceilings differ by statistic.** Control: box-downscale the 4K frame to 1080 and lanczos-upscale it back, then
  score the 4K frame against that. For the Sobel ratio the ceiling is at most 1.000 (flag) and 0.975 / 0.909 / 0.920
  (zoom), which is why the first gate could not pass. For the Laplacian ratio the ceilings are flag 2.03 / 3.06 / 4.02 and
  zoom 3.10 / 5.76 / 6.97.
- **Where the candidates sit against their ceilings.** `flag` (and `scale`) reach 1.82 / 2.25 / 2.50, which is 90 %, 73 %
  and 62 % of the ideal: below it, by a growing margin at the later instants. `zoom` reaches 4.74 / 5.96 / 5.38, which is
  153 %, 104 % and 77 % of its ideal, so it is nearer to it (and above it at the first two instants, i.e. more fine-scale
  edge energy than the downscale-upscale control; plausible because CSS zoom re-rasterises the glyphs at 2x). So by this
  statistic `zoom` is the crisper render and `flag` is not at its ideal; the lead's look at the crops found them visually
  equal, and `flag` passes the gate at every instant.
- **Reading the number.** Laplacian variance rewards any fine-scale edge energy, so it is not a fidelity measure on its
  own (an unsharp mask scores 12 to 31). It tells "not softer than a 2x upscale"; `geom` is what says the picture is the
  same one. Other statistics that react to edge width (information only): p99 of the Sobel magnitude, 4K over upscaled,
  is flag 1.00 / 1.13 / 1.14, zoom 1.01 / 1.30 / 1.24.

Reproduce: set `FT_SPIKE_COMP` to a finished export folder (its `index.html` and `assets/`; the script exits with a message
without it), then `.venv/Scripts/python dev/spike4k/run.py <short work folder> install | help | telemetry | offline | prep4k | cands | measure`.
`measure` re-extracts frames 24, 60, 110 from the existing renders and recomputes everything; it does not re-render.
