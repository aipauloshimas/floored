# Fonts (Task 4)

All fonts are SIL OFL 1.1 and come from github.com/google/fonts, commit `5bb28733cec313b63fbd415b574b5ae35c8aa8b8`
(fetched 2026-11-08). `dev/gen_metrics.py` downloads them to `dev/fonts-src/` (git-ignored; the source TTFs are not in the
repository) and writes the subset woff2 files plus `metrics.js`.

URL pattern: `https://raw.githubusercontent.com/google/fonts/5bb28733cec313b63fbd415b574b5ae35c8aa8b8/ofl/<path>`

| Font id | File | Source path | Instanced at |
|---|---|---|---|
| condensed (Anton) | anton.woff2 | anton/Anton-Regular.ttf | static |
| serif (Instrument Serif) | serif.woff2 | instrumentserif/InstrumentSerif-Regular.ttf | static |
| geo (Poppins Black) | geo.woff2 | poppins/Poppins-Black.ttf | static |
| mono (JetBrains Mono Bold) | mono.woff2 | jetbrainsmono/JetBrainsMono[wght].ttf | wght 700 |
| stencil (Big Shoulders Stencil) | stencil.woff2 | bigshouldersstencil/BigShouldersStencil[opsz,wght].ttf | wght 900, opsz 14 |
| hand (Gochi Hand) | gochihand.woff2 | gochihand/GochiHand-Regular.ttf | static |
| UI and fallback (Inter) | inter.woff2 | inter/Inter[opsz,wght].ttf | opsz 14, wght axis kept (100-900) |

Each OFL.txt sits next to the family in the same folder of google/fonts. The woff2 files keep the fonts' name tables
(copyright and license strings).

Subset: `CHARSET` in `gen_metrics.py` (U+0020-007E, U+00A0-00FF, U+0100-017F, and ’ ‘ “ ” – — … €, without U+00AD and
U+0149), `ccmp` as the only layout feature (the engine turns kern, liga and calt off), hinting kept. Inter also keeps
• ← ↑ → ↓ for the studio UI.

Characters a font lacks (the `FALLBACK_OK` lists in `gen_metrics.py`): Gochi Hand has no Latin Extended-A to speak of;
the other fonts only miss rare letters (ĉ, ĳ, ħ ...) and, for Instrument Serif, a few Latin-1 symbols. Inter draws those,
scaled with CSS `size-adjust` (`fbAdj` in metrics.js) so its cap height matches the font's.
