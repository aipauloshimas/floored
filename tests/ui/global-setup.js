// Makes the two 1 s clips the upload tests use (ffmpeg testsrc2, 9:16): tests/ui/.fixtures/{clip_1080.mp4, clip_4k.mp4}.
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const DIR = path.join(__dirname, '.fixtures');
const CLIPS = [['clip_1080.mp4', '1080x1920'], ['clip_4k.mp4', '2160x3840']];

module.exports = async function globalSetup() {
  fs.mkdirSync(DIR, { recursive: true });
  for (const [name, size] of CLIPS) {
    const out = path.join(DIR, name);
    if (fs.existsSync(out) && fs.statSync(out).size > 0) continue;
    const r = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'lavfi', '-i', `testsrc2=size=${size}:rate=24:duration=1`,
      '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', out], { encoding: 'utf8' });
    if (r.status !== 0) throw new Error(`ffmpeg could not make ${name}: ${r.stderr || r.error}`);
  }
};
