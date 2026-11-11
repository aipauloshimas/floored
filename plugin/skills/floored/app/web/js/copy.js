/* The words and numbers the creator reads: the filming guide, honest wait times and the export output line.
   One place, so the home screen, the export dialog and reference/filming.md (which Claude's skill shows) agree.
   A test checks that filming.md carries every rule below, word for word. */

/* ---- the filming guide: `title` and `text` are shown on the home screen and appear verbatim in reference/filming.md */
export var FILMING = {
  heading: 'How to film it',
  rules: [
    { icon: 'phone', title: 'Phone up high, looking down',
      text: 'Put it about 3 m up and 2 m in front of you, tilted down at about 45–50°, so your legs and shoes show. Not straight down. Use the 1× lens, not the ultra-wide.' },
    { icon: 'frame', title: 'Room around you',
      text: 'Stand in the middle, with about 20% free space on every side. Keep your arms inside the frame.' },
    { icon: 'pin', title: 'Stay on one spot',
      text: 'Move your arms and face, not your feet.' },
    { icon: 'clock', title: '3 to 8 seconds',
      text: 'Say your line to the lens.' },
    { icon: 'sun', title: 'Good light, plain floor',
      text: 'Even light and a floor with no pattern look best.' }
  ],
  diagramAlt: 'Side view: the phone about 3 m up and 2 m in front of you, tilted down at about 45–50°, not straight above you.',
  examplesHeading: 'Good take, bad take',
  /* two takes, each with the intro it gives; "take" and "intro" are file names in img/filming/ */
  pairs: [
    { good: true, label: 'Film it like this', take: 'good-take', intro: 'good-intro',
      title: 'Your whole body stands on the words.',
      text: 'Legs and shoes in the shot, room on every side.',
      takeAlt: 'A take filmed from about 45 degrees: the whole body is in the shot, legs and shoes too.',
      introAlt: 'The intro made from that take: the words lie on the floor around the whole body.' },
    { good: false, label: 'Not from straight above', take: 'above-take', intro: 'above-intro',
      title: 'Your legs and feet go missing.',
      text: 'From straight above they hide under your body. Film from further back.',
      takeAlt: 'A take filmed from straight above: a large head and chest, the legs hidden below.',
      introAlt: 'The intro made from that take: the legs and feet are hardly visible.' }
  ],
  mistakes: [
    { img: 'too-close', label: 'Too close',
      text: 'Part of you leaves the frame, and it ends in a straight cut. Leave room on every side.',
      alt: 'A take filmed too close: the person fills the frame and their hands run off the edge.' },
    { img: 'walking', label: 'Walking',
      text: "Your feet move, so the words don't stay lined up with you. Stand on one spot.",
      alt: 'A take of a person walking, seen from above and moving off to one side of the frame.' },
    { img: 'two-people', label: 'Two people',
      text: 'floored works best with just you.',
      alt: 'A take with two people standing side by side.' }
  ]
};

/* ---- waiting */
/* "About 4 min left" (rounded up), "Less than a minute left" under 60 s; while the speed is only a guess, say so. */
export function etaText(eta, guess) {
  if (typeof eta !== 'number' || !isFinite(eta) || eta < 0) return '';
  var mins = Math.max(1, Math.ceil(eta / 60));
  if (guess) return 'About ' + mins + ' min (first run, rough guess)';
  return eta < 60 ? 'Less than a minute left' : 'About ' + mins + ' min left';
}

/* seconds of wall-clock per frame, used until /api/info answers (the server's own defaults) */
export var RENDER_SEC_PER_FRAME = { '1': 1.3, '2': 2.7 };

function minutes(frames, secPerFrame) { return Math.max(1, Math.ceil((frames || 0) * secPerFrame / 60)); }
/* "Export: about 3 min" for a 1080 take, "4K export: about 3 min" for a 4K one */
export function exportEstimateText(frames, secPerFrame, is4K) {
  return (is4K ? '4K export' : 'Export') + ': about ' + minutes(frames, secPerFrame) + ' min';
}
/* the line above the steps while the render runs */
export function exportRunningText(frames, secPerFrame, is4K) {
  return 'Rendering your intro. ' + (is4K ? 'A 4K render takes longer, about ' + minutes(frames, secPerFrame) + ' min.' : 'This usually takes a few minutes.');
}

/* ---- the output line */
/* a frame rate as a person says it: 24000/1001 -> "23.976", 30000/1001 -> "29.97", 60000/1001 -> "59.94", 30 -> "30".
   "" when it cannot be read: the caller then says nothing about the rate rather than a wrong one. */
export function fpsLabel(v) {
  var n, parts;
  if (typeof v === 'string' && v.indexOf('/') > 0) { parts = v.split('/'); n = parseFloat(parts[0]) / parseFloat(parts[1]); }
  else n = typeof v === 'number' ? v : (typeof v === 'string' && /^\s*[0-9.]+\s*$/.test(v) ? parseFloat(v) : NaN);
  if (!isFinite(n) || n <= 0) return '';
  return String(Number(n.toFixed(3)));
}

/* what the export will be, from the take's own numbers (a take saved before they existed falls back to its stage size and fps).
   `fps` is '' when none of them can be read. */
export function takeOutput(take) {
  var o = take && take.out, t = take || {};
  var fps = fpsLabel(o && o.fpsStr) || fpsLabel(o && o.fps) || (o ? '' : fpsLabel(t.fps));
  return { w: (o && o.w) || t.w || 1080, h: (o && o.h) || t.h || 1920, fps: fps };
}
function sizeFps(o) { return 'MP4 · ' + o.w + ' × ' + o.h + (o.fps ? ' · ' + o.fps + ' fps' : ''); }
/* "matches your take" is only said when the rate is known */
export function outputLine(take) {
  var o = takeOutput(take);
  return sizeFps(o) + (o.fps ? ' · matches your take' : '');
}
export function resultLine(take) { return sizeFps(takeOutput(take)); }

/* ---- when the studio's server cannot be reached (the banner, the failed save, the failed render) */
export var REACH = {
  banner: 'The studio stopped. Go back to Claude and say: open floored again.',
  unreachable: 'The studio stopped.',
  saveKept: 'Your last change is kept on this page. It is saved when the studio is back.',
  renderTitle: 'The render did not finish',
  renderGone: 'The studio stopped.',
  renderGoneNote: 'Your changes are kept on this page and are saved when the studio is back. Then you can render again.',
  renderBackNote: 'The studio is back. You can try again.'
};
