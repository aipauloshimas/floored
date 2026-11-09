# Acceptance run, 2026-11-09 (Task 24, non-G1 parts)

Design section 15. No footage is in the repo: the clips below were made with ffmpeg from the repo's own sample
(`app/sample/source.mp4`, AI-generated) into a temp folder, and the exports are the sample's.

| Part | Status |
|---|---|
| 15.2 three phone-like takes, drop to export, feet within 15 px (step 1) | PASS on AI takes, 3 of 3 (table 6). Real phone files: not tested (known gap) |
| 15.5 real warnings: edge, moved, people, noperson (step 2, real half) | 4 of 5 (table 7): edge, moved, legs and noperson fire; people misses two people who touch |
| 15.5 synthetic warnings: short, long, landscape, lowres, aspect, hdr | PASS, 6 of 6 (table 1) |
| 15.3 export matches the studio, 6 looks x 3 instants, SSIM >= 0.95 | PASS, 6 of 6 looks, 18 of 18 comparisons (table 2). Round 1 found the cause (the H.264 bitrate-mode encode); round 2 changed the export encode (section 4). |
| 15.4 export table (size, fps, bitrate, LUFS, AAC 48 kHz) | PASS, 6 of 6 rows on the round-2 exports (table 3; bitrate rule 0.98 x max(take, 8 Mbps), raw numbers shown) |

## 1. Synthetic warnings (15.5)

Each clip was run through the built pipeline (`serve` a temp workspace, `add`, `wait`, real cutout, no fake matte) and the
warning codes in the take's check were read. The target code must fire once.

| Clip (made from the sample) | Target | Codes fired | Target once? | Other codes |
|---|---|---|---|---|
| `short.mp4`: first 2 s | short | short, edge | yes | edge (allowed: the sample person touches an edge) |
| `long.mp4`: sample looped to 9 s | long | long, edge | yes | edge (allowed) |
| `landscape.mp4`: 1920x1080, sample letterboxed in the middle | landscape | landscape, lowres, aspect | yes | lowres and aspect follow from the shape: any 1920x1080 clip has them (the unit test expects the same three) |
| `lowres.mp4`: 540x960 | lowres | lowres, edge | yes | edge (allowed) |
| `aspect.mp4`: 1080x1440 (3:4), sample scaled to fit and padded | aspect | aspect, moved | yes | moved (allowed: the scaled person's feet shift) |
| `hdr.mp4`: HLG 10-bit HEVC, bt2020, `zscale` to arib-std-b67 | hdr | hdr, edge | yes | edge (allowed) |

Result: 6 of 6 pass. Each target fired exactly once. Besides the targets, only edge, moved, lowres and aspect appeared, and
the last two only where the clip shape forces them (landscape); no synthetic code (short, long, landscape, hdr) fired on a clip it did not belong to.

Notes on making the clips: the sample carries no colour tags, so the HDR copy needs `setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv`
before the first `zscale` (otherwise zscale says "no path between colorspaces"); then
`zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt2020,zscale=t=arib-std-b67,zscale=m=bt2020nc:r=tv,format=yuv420p10le`
into `libx265 -pix_fmt yuv420p10le -tag:v hvc1` with the bt2020/arib-std-b67 tags.

## 2. Studio vs export (15.3): `tests/ui/match.spec.js`

Run: `npm run test:match` (config `playwright.match.config.js`; about 2 to 7 min per look (126 to 392 s in round 2, on a shared PC); `FT_MATCH_LOOKS=terminal,sketch`
picks looks, `FT_MATCH_OUT` keeps the frames, the mp4s and `match-results.json`). For each look it opens the sample, picks
the look, photographs the studio stage (`window.__ft.seek`, pinned to 540x960 CSS px at device scale 2 = 1080x1920 real
pixels), presses the real Export button, waits for the render, and compares both frames at 540x960 (lanczos) with ffmpeg
`ssim` ("All:"). The instants are the frames at or before t: 14 (0.583 s), 48 (2.0 s), 110 (4.583 s); the studio is asked
for that same frame time. Bar: SSIM >= 0.95 (design threshold, not loosened).

Round-2 exports (render at CRF 8, our own encode at CRF 14; before = the shipped bitrate-mode export of round 0):

| Look | t = 0.6 (frame 14) | t = 2.0 (frame 48) | t = 4.6 (frame 110) | Result | Before (0.6 / 2.0 / 4.6) |
|---|---|---|---|---|---|
| original | 0.9923 | 0.9873 | 0.9815 | PASS | 0.9937 / 0.9802 / 0.9744 |
| noir | 0.9867 | 0.9896 | 0.9919 | PASS | 0.9740 / 0.9851 / 0.9880 |
| editorial | 0.9843 | 0.9930 | 0.9939 | PASS | 0.9849 / 0.9900 / 0.9923 |
| terminal | 0.9664 | 0.9602 | 0.9629 | PASS | 0.9241 / 0.9300 / 0.9274 (FAIL) |
| loud | 0.9790 | 0.9777 | 0.9800 | PASS | 0.9796 / 0.9774 / 0.9800 |
| sketch | 0.9826 | 0.9860 | 0.9815 | PASS | 0.9185 / 0.9556 / 0.9653 (FAIL at 0.6) |

Result: 6 of 6 looks pass, 18 of 18 comparisons are at or over 0.95 (lowest: terminal 0.9602 at t = 2.0). The bar was not touched.
Before the round-2 change 4 of 6 passed. Why the two grain looks failed, and what fixed them, is section 4.

Spec corrections made while building it (they explain the first run's numbers of 0.91 to 0.96, which were harness faults
and are gone): the person's alpha video seeks slowly (seconds on a busy laptop), so the spec waits for both videos to
finish seeking; and the studio stage is pinned to exactly 540x960 CSS px at device scale 2 instead of a fractional fit.

## 3. Export table (15.4): `dev/bench/export_table.py`

`python dev/bench/export_table.py FOLDER` reads a folder of mp4s and prints this table (`--take` picks the take.json or
source video to judge against; the default is the sample's take.json). Rules: size and fps equal the take's, same frame
count, video bitrate >= 0.98 x max(take bitrate, 8 Mbps) (the approved plan's rule, the same one `ft/export.py` applies;
the raw Mbps is printed next to it), integrated loudness -14 +- 1 LUFS, true peak <= -1.0 dBTP (+0.1 dB of measuring
slack), AAC at 48 kHz. The sample's own bitrate is 5.37 Mbps, so the 8 Mbps floor applies. The six files are the exports of table 2.

| file | take | size | fps, frames | video Mbps (raw, need, min = 0.98 x need) | LUFS (-14 +-1) | true peak dBTP | audio | size | result |
|---|---|---|---|---|---|---|---|---|---|
| editorial.mp4 | Sample take | 1080x1920 | 24 fps, 121 fr | 22.46 (need 8.00, min 7.84) | -13.8 | -2.0 | aac 48 kHz | 14.3 MB | PASS |
| loud.mp4 | Sample take | 1080x1920 | 24 fps, 121 fr | 8.42 (need 8.00, min 7.84) | -13.7 | -2.0 | aac 48 kHz | 5.4 MB | PASS |
| noir.mp4 | Sample take | 1080x1920 | 24 fps, 121 fr | 16.68 (need 8.00, min 7.84) | -14.0 | -1.7 | aac 48 kHz | 10.6 MB | PASS |
| original.mp4 | Sample take | 1080x1920 | 24 fps, 121 fr | 10.02 (need 8.00, min 7.84) | -14.0 | -1.7 | aac 48 kHz | 6.4 MB | PASS |
| sketch.mp4 | Sample take | 1080x1920 | 24 fps, 121 fr | 22.18 (need 8.00, min 7.84) | -13.9 | -1.0 | aac 48 kHz | 14.1 MB | PASS |
| terminal.mp4 | Sample take | 1080x1920 | 24 fps, 121 fr | 25.04 (need 8.00, min 7.84) | -13.7 | -1.6 | aac 48 kHz | 15.9 MB | PASS |

6 of 6 rows pass.

Before (round 0, bitrate mode) the same six looks were 5.1 to 6.7 MB at 7.95 to 10.36 Mbps; now they are 5.4 to 15.9 MB
(section 4 has the per-look before and after).

Notes:
- The rule is 0.98 x 8.00 = 7.84 Mbps. Five looks come out of the CRF 14 encode well above it (10.0 to 25.0 Mbps). loud is the
  one where CRF gave 4.97 Mbps (a quiet, flat picture), so the floor re-encode ran: two-pass from the same intermediate at
  8.40 Mbps, giving 8.42 Mbps, 5.4 MB.
- sketch's true peak is -1.0 dBTP, on the target (-1.0) and inside the 0.1 dB slack.
- Tier-2 (4K) export: none exists in this run's temp folders (the pytest `test_tier2` makes one and checks it itself), so no
  4K row. 60 fps and HEVC-source takes belong to step 1 (real phone takes, lead).

## 4. Round 1: why the grain looks fail (terminal, sketch)

Question: the grain is deterministic (`gi = round(t*fps) % 6`, seed `7000 + gi*977`), so why did the studio and the export
disagree at 0.92? Method: measure each hop separately, change nothing until the cause is known.

| Hop | Evidence | Verdict |
|---|---|---|
| fps differs between studio and export | `engine.fps` is 24 in the export page, the studio take's fps is 24 | ruled out |
| grain canvas size differs | both are `<canvas class="ft-grain" width="540" height="960">` (preview.js, composition.html); computed CSS size 1080x1920 in both | ruled out |
| `_gi` cache skips a repaint after a seek | the export page's `_gi` is 2, 0, 2 at frames 14, 48, 110 (= n % 6) | ruled out |
| grain pixels differ | grain canvas read back with `getImageData` in the studio (after `__ft.seek`) and in the export page (`__timelines.main.seek`): byte sums identical at frames 14, 48 and 110 (66373925, 66312649, 66373925) | engine is deterministic |
| HyperFrames capture differs from the studio | a lossless render (`--crf 0`) of the sample's export project, frames 14, 48, 110 against the studio PNGs: sketch 0.9902 / 0.9921 / 0.9922, terminal 0.9829 / 0.9785 / 0.9738 | capture is faithful |
| the lossy encode | the real export (single pass, `-b:v 9M`, `-bf 0`, `aq-mode=3:aq-strength=0.8`) keeps the grain for frames 0 to 11 (correlation with the studio noise 0.84 falling to 0.68), then freezes it: from frame 12 on, consecutive frames differ by under 0.05 grey levels in a flat floor patch (2.1 before), and the patch correlates 0.13 with the studio's | **root cause** |

So the engine is innocent. Rate control, once it has spent the start-up bits, treats the +-2 grey level grain as noise to drop
and copies the previous picture into the floor. No engine change can fix that, and none was needed: the studio and the lossless
export are the same picture to 0.97 to 0.99.

What a different encode does (HyperFrames' own encoder arguments replayed on the lossless frames, then confirmed by a real
render with `hyperframes render --crf 18`; SSIM at 0.6 / 2.0 / 4.6 s against the studio):

| Encode | sketch | terminal | editorial | Mbps (sketch / terminal / editorial) |
|---|---|---|---|---|
| shipped: `--video-bitrate 9M` | 0.9185 / 0.9556 / 0.9653 | 0.9241 / 0.9300 / 0.9274 | 0.9849 / 0.9900 / 0.9923 | 10.4 / 8.9 / 7.95 |
| `--crf 18` (real HyperFrames render) | 0.9708 / 0.9701 / 0.9708 | 0.9555 / 0.9445 / 0.9443 | 0.9910 / 0.9910 / 0.9918 | 16.5 / 15.1 / 6.36 |
| x264 crf 14 (replay) | n/a | 0.9686 / 0.9595 / 0.9589 | n/a | n/a / 29.3 / n/a |
| x264 crf 10 (replay) | 0.9858 / 0.9882 / 0.9882 | 0.9761 / 0.9690 / 0.9671 | n/a | 66.9 / 52.3 / n/a |
| ABR variants (slow preset, `-tune grain`, no mbtree), replay | 0.93 to 0.98, about 0.947 at 2.0 s | 0.918 to 0.951 | n/a | 11 to 13 |

Findings for the decision (not made here; the 0.95 bar and the export rules are untouched):
- Constant quality is what keeps grain: `--crf 18` brings sketch over the bar at all three instants; terminal needs about crf 14,
  which is 29 Mbps (18 MB for a 5 s take, over the 30 MB phone limit at 8 s).
- Constant quality breaks the bitrate floor on flat looks: editorial at crf 18 is 6.36 Mbps (< 7.84), though it scores 0.991. A
  take whose own bitrate is high (a 4K phone take) also asks for more than crf gives. `--crf` and `--video-bitrate` exclude each other in HyperFrames.
- Bitrate mode at the floor cannot hold a grain this faint; going to 20 to 30 Mbps helped only partly in replay (0.953 to 0.961 at 2.0 s).
- Options: (a) per look: grain looks render with a CRF and are checked against the floor afterwards; (b) a render-then-encode step
  (lossless or crf 10 intermediate, then our own 2-pass encode); (c) make the grain survive an encode (bigger amplitude or
  coarser grain, a look change); (d) judge the grain looks on the lossless capture and say so.
- Engine change made: only a pure seam (`Floored.grain.index` / `.fill`), byte-identical output, pinned by
  `tests/js/grain.test.js` (pixel hashes of the six noise frames, frame index per fps, canvas size in both markups).

### Round 2: the export encode changed (`ft/export.py`)

Ruling: keep every design promise, change neither the 0.95 bar nor any look. The export is now two steps:
1. HyperFrames renders a near-lossless intermediate, `--crf 8` (instead of `--video-bitrate`), to `render.mp4` in the export folder.
   `--fps`, `--resolution portrait-4k` (tier 2), the telemetry opt-out, the player-ready timeout and the scaled timeout are unchanged.
2. Our ffmpeg encodes it: `libx264 -crf 14 -preset slow -pix_fmt yuv420p`, BT.709 tags written into the H.264 stream through `-x264-params` (ffmpeg 8.1 ignores the `-color_primaries` / `-color_trc` output options; a test encodes an untagged source and probes the result), limited range, `+faststart`, timestamps passed
   through. Then the existing mix step copies that video and adds the AAC track, so the audio is still muxed once.
3. Floor: the encode's video bitrate is measured; below max(take, 8 Mbps), the same intermediate is encoded again two-pass
   at ceil(max(take, 8 Mbps) x 1.05) (8.40 Mbps for a normal take). `check_output` (>= 0.98 x floor, size, fps, frames, LUFS, AAC 48 kHz)
   is unchanged and still runs before `done`.
4. `render.mp4` is deleted after a successful export. After a failure it stays, and `export.log` says where
   ("kept the intermediate at <path>", one line for any failure that leaves it: render, encode, mix, check or a bug). `export.log` also records the CRF result ("encode: crf 14 slow gives X Mbps, Y MB; floor Z Mbps")
   and whether the floor re-encode ran; `details.encode` carries {crf, crfBitrate, floorMbps, floorReencode, bitrate}.
5. Render speed (`machine.json`) stays wall-time based and now covers render + encode.
6. `dev/bench/make.py` does not render videos (its goldens and `--compare` are stills made with `hyperframes snapshot`); it shares only
   `renderer_bin` and `renderer_env`, so it is unchanged and stays comparable to `tests/golden`.

Colour tags of the final file (ffprobe): High profile, yuv420p, tv range, bt709 primaries / transfer / matrix, same as before. Two
differences from the old HyperFrames file: x264 picks level 5.0 (was 4.0) and the slow preset uses B-frames (`has_b_frames` 2, was 0).

Per look, before (shipped `-b:v 9M`) and after, 1080x1920, 24 fps, 121 frames, the 5.04 s sample. Wall times come from `export.log`
on a shared PC (other jobs were running in both runs), so they are indicative, not a benchmark:

| Look | Mbps before > after | MB before > after | render + encode s before > after (total export s) | Floor re-encode |
|---|---|---|---|---|
| original | 10.29 > 10.02 | 6.6 > 6.4 | 637 > 190 + 28 (685 > 225) | no |
| noir | 8.98 > 16.68 | 5.8 > 10.6 | 371 > 210 + 50 (388 > 269) | no |
| editorial | 7.95 > 22.46 | 5.1 > 14.3 | 204 > 76 + 42 (215 > 125) | no |
| terminal | 8.86 > 25.04 | 5.7 > 15.9 | 348 > 135 + 45 (360 > 188) | no |
| loud | 9.10 > 8.42 | 5.9 > 5.4 | 220 > 105 + 22 (230 > 132) | yes: CRF 4.97 Mbps, two-pass 8.42 Mbps |
| sketch | 10.36 > 22.18 | 6.7 > 14.1 | 367 > 320 + 59 (376 > 391) | no |

Total export time went down for five looks (original 685 > 225 s, noir 388 > 269, editorial 215 > 125, terminal 360 > 188, loud 230 > 132)
and up for one (sketch 376 > 391 s: render 320 s, encode 59 s). The PC was shared both times, so these are not a benchmark and the
render stage alone (shorter in all six) says little. The CRF 14 encode adds 22 to 59 s at 1080 (about 0.2 to 0.5 s per frame). 4K (`test_tier2`, a 20 Mbps take): render 394 s + encode 154 s, total 581 s; no 4K figure
from before the change was kept.  loud's 22 s includes the CRF encode and both floor passes.

Sizes grow where the grain or the busy picture needs the bits (terminal 15.9 MB for 5 s is about 25 Mbps; a 10 s take of that look
would be near 32 MB, over the 30 MB phone-limit copy; the phone copy is a separate, lighter file made on request). Looks that
were already above the floor (original, loud) are about the same size as before.

Tests: `tests/py/test_export.py` fast tests pin the command lines (`render_cmd` CRF render and tier-2 flag, `encode_cmd`, `abr_cmds`)
and the floor fallback through a fake stream and a fake probe (CRF clears the floor, falls back at 6.36 Mbps, the floor is the take's
own bitrate above 8 Mbps, a failed encode keeps the intermediate); the slow `test_sample_original` and `test_tier2` pass on the real
renderer (tier 2: `--crf 8` in the log, 2160x3840, 20 Mbps floor held).

## 5. Step 1 and the real warnings (lead, calibration takes)

The takes were AI-generated (gate G1: no real phone files), so they stay private and outside the repo. They were checked
by the lead against hand-marked points between the soles, at 1080 scale. The full write-up is in the private
calibration doc.

**Table 6, step 1.** Three phone-like copies of one AI take, filmed at the guide's angle (about 50°): an iPhone-like HEVC
stream stored landscape with a −90° rotation tag, an Android-like 30 fps H.264 and a 60 fps copy. Each went from `add`
to the studio's Export button.

| Copy | Cutout frames | Feet vs mark | Warnings | Export | Bitrate | LUFS | Audio | Result |
|---|---|---|---|---|---|---|---|---|
| iPhone-like HEVC, rotated, 24 fps | 121 of 121, upright | 6 px | none | 1080×1920, 24 fps, 121 fr | 9.50 Mbps | −14.2 | AAC 48 kHz | PASS |
| Android-like H.264, 30 fps | 151 of 151 | 6 px | none | 1080×1920, 30 fps, 151 fr | 10.65 Mbps | −14.2 | AAC 48 kHz | PASS |
| 60 fps | 303 of 303 | 6 px | none | 1080×1920, 60 fps, 303 fr | 14.05 Mbps | −14.2 | AAC 48 kHz | PASS |

The other takes at the guide's angle land 4 and 17 px from their marks. The 17 px one has white shoes on a black floor,
whose edges fade. A steep take lands 11 px off.

**Table 7, step 2 (real half).**

| Code | Take | Fires? |
|---|---|---|
| edge | hands reach the frame edge | yes |
| moved | the person walks out of frame | yes |
| legs (new) | filmed almost straight down: the cutout ends at the hips | yes (2 of 2) |
| noperson | a floor-only crop of a take (G1b) | yes: the take stops with "We couldn't find a person in this clip…", which is stronger than a warning |
| people | two people standing shoulder to shoulder, touching | **no**: the cutout is one shape. This is a known limit; no take of two people standing apart was available |

## 6. Still to do

- The Haiku re-run of the table is for the controller: `python dev/bench/export_table.py <folder of the six mp4s>`.
- Real phone files (iPhone HEVC portrait, Android, 60 fps) remain a known gap.
