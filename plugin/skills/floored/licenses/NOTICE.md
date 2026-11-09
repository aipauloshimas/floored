# Notices

floored's own code is MIT (see `LICENSE` at the repository root). This file says what else is involved and under
which licence. Nothing listed as "installed at setup" is part of this repository or of the plugin package: setup
downloads it to your computer from the official source, and it stays there.

## Installed at setup (never bundled)

- **Robust Video Matting weights, `rvm_mobilenetv3_fp32.onnx`** (the model that cuts you out of the video).
  GPL-3.0. Downloaded at setup from the official release,
  https://github.com/PeterL1n/RobustVideoMatting/releases/tag/v1.0.0 , and never bundled. This is the default (MobileNetV3)
  model; floored does not use the ResNet variant. The weights are kept in `~/.cache/rvm`. floored only loads them with
  onnxruntime; it does not include or modify them.
- **HyperFrames**, the video renderer, pinned to 0.9.22. Apache-2.0. Installed at setup with npm into `~/.floored`.
- **onnxruntime** (the DirectML build on Windows, the standard build on macOS). MIT. Installed at setup with pip.
- **numpy**. BSD-3-Clause. Installed at setup with pip.
- **faster-whisper and the Whisper weights** (optional, to read words from your speech; the `base` model, from the
  `Systran/faster-whisper-base` repository). MIT. Installed at setup with pip, only when you accept it.
- **Optional speech reader, installed with faster-whisper by pip** (same consent): ctranslate2 (MIT), av (BSD-3-Clause),
  tokenizers (Apache-2.0) and huggingface-hub (Apache-2.0).
- **Chrome headless shell**, the browser HyperFrames downloads on its first render, into `~/.cache/hyperframes` (or
  `~/.floored/hf-cache`). Google's Chrome for Testing build, under the Chromium project's licences (BSD-3-Clause and
  others). Installed, not bundled.

## Bundled in this repository

- **GSAP 3.14.2**, under GreenSock's standard "no charge" licence. See `licenses/GSAP.md`, which links
  https://gsap.com/standard-license .
- **Fonts**: Anton, Instrument Serif, Poppins, JetBrains Mono, Big Shoulders Stencil, Gochi Hand and Inter, all under the
  SIL Open Font License 1.1. The licence texts are the `OFL-*.txt` files in this folder. Two fonts carry a copyright line
  of their own that differs from the one on the licence text, so both are given:
  - Inter: the font file says "Copyright 2016 The Inter Project Authors (https://github.com/rsms/inter)"; the `OFL.txt`
    of the family says 2020.
  - Gochi Hand: the font file says "Copyright (c) 2011, Huerta Tipografica (www.huertatipografica.com.ar), with Reserved
    Font Names "Gochi" and "Gochi Hand""; the `OFL.txt` of the family says "Juan Pablo del Peral
    (juandelperal@htfonts.com)". The font's trademark notice ("Gochi Hand is a trademark of Juan Pablo del Peral") is also
    kept. See `THIRD_PARTY.md` for why the bundled copy is named "FT Hand".
- **Sample take** in `app/sample/`: an AI-generated video. See `app/sample/README.md`.
