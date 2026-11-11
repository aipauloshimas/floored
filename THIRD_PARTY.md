# Third-party software and fonts

floored's own code is MIT (see `LICENSE`). Everything below keeps its own licence. The full texts and notes are in
`plugin/skills/floored/licenses/`.

## Bundled in this repository

| What | Where | Licence | Notes |
|---|---|---|---|
| Anton | `app/web/engine/fonts/anton.woff2` | SIL OFL 1.1 | `licenses/OFL-Anton.txt` |
| Instrument Serif | `app/web/engine/fonts/serif.woff2` | SIL OFL 1.1 | `licenses/OFL-InstrumentSerif.txt` |
| Poppins (Black) | `app/web/engine/fonts/geo.woff2` | SIL OFL 1.1 | `licenses/OFL-Poppins.txt` |
| JetBrains Mono (Bold) | `app/web/engine/fonts/mono.woff2` | SIL OFL 1.1 | `licenses/OFL-JetBrainsMono.txt` |
| Big Shoulders Stencil (weight 900) | `app/web/engine/fonts/stencil.woff2` | SIL OFL 1.1 | `licenses/OFL-BigShouldersStencil.txt` |
| Gochi Hand | `app/web/engine/fonts/gochihand.woff2` | SIL OFL 1.1 | `licenses/OFL-GochiHand.txt` |
| Inter (studio interface and fallback) | `app/web/engine/fonts/inter.woff2` | SIL OFL 1.1 | `licenses/OFL-Inter.txt` |
| GSAP 3.14.2 | `app/web/engine/gsap.min.js` | GreenSock standard "no charge" licence | `licenses/GSAP.md` |

The font files are subsets of the families published at https://github.com/google/fonts (the licence text of each
family is copied from the same folder there). Subsetting and instancing keep the fonts' own name tables, including
their copyright and licence strings.

**Reserved Font Names.** Only Gochi Hand reserves its names ("Gochi" and "Gochi Hand"). A subset is a Modified Version,
which the OFL (section 3) forbids from using a Reserved Font Name, so the bundled `gochihand.woff2` is renamed "FT Hand"
in its name table (the family, full and PostScript names). Its copyright and trademark notices are kept as they are, and
`dev/gen_metrics.py` applies the rename whenever it rebuilds the font. The other six licences reserve nothing.

`app/sample/` holds one AI-generated sample take so you can try the skill; it is under the same MIT licence as the code
(see `app/sample/README.md`).

`app/web/img/filming/` holds the filming guide's pictures: stills from AI-generated test clips, so the people in them
don't exist. They are under the same MIT licence as the code.

## Installed at setup, never bundled

Downloaded or installed on your computer by the setup step, from their official sources. See
`licenses/NOTICE.md`.

| What | Licence |
|---|---|
| Robust Video Matting weights (`rvm_mobilenetv3_fp32.onnx`) | GPL-3.0 |
| HyperFrames (pinned 0.9.22) | Apache-2.0 |
| onnxruntime (DirectML build on Windows) | MIT |
| numpy | BSD-3-Clause |
| faster-whisper and the Whisper weights (optional) | MIT |

## Development only

Playwright (`@playwright/test`) and the Python test tools in `requirements-dev.txt` are used to test floored. They are
not part of the plugin.
