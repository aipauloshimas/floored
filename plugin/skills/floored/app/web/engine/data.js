/* floored: the shared data (fonts, palettes, ready looks, option labels). The engine, the studio and
   the export all read it. */
(function (root) {
  var FONTS = {
    condensed: { label: 'Condensed', family: 'FT Condensed', file: 'anton.woff2', weight: 400, ls: 0 },
    serif:     { label: 'Editorial serif', family: 'FT Serif', file: 'serif.woff2', weight: 400, ls: -0.01 },
    geo:       { label: 'Geometric', family: 'FT Geo', file: 'geo.woff2', weight: 900, ls: 0 },   // tighter ran words together
    mono:      { label: 'Mono', family: 'FT Mono', file: 'mono.woff2', weight: 700, ls: -0.04 },
    stencil:   { label: 'Stencil', family: 'FT Stencil', file: 'stencil.woff2', weight: 900, weightRange: '100 900', ls: 0.01 },
    hand:      { label: 'Hand-drawn', family: 'FT Hand', file: 'gochihand.woff2', weight: 400, ls: 0 }
  };

  // floor = the virtual floor, ink = the words, small = the small typed line
  var PALETTES = [
    { id: 'sage-red',         label: 'Sage & red',         floor: '#C8CEBF', ink: '#E0161A', small: '#5C1515' },
    { id: 'paper-ink',        label: 'Paper & ink',        floor: '#ECEAE4', ink: '#121212', small: '#6E6A63' },
    { id: 'noir',             label: 'Noir',               floor: '#1A1A1C', ink: '#F2F0EA', small: '#8C8A85' },
    { id: 'cream-navy',       label: 'Cream & navy',       floor: '#F1E9D8', ink: '#14244B', small: '#8A6F45' },
    { id: 'yellow-black',     label: 'Yellow & black',     floor: '#F6D21C', ink: '#111111', small: '#5A4A00' },
    { id: 'pink-wine',        label: 'Pink & wine',        floor: '#F4C9D1', ink: '#6E0F2A', small: '#B0485F' },
    { id: 'graphite-lime',    label: 'Graphite & lime',    floor: '#2A2B2E', ink: '#C8F031', small: '#8C8F95' },
    { id: 'white-cobalt',     label: 'White & cobalt',     floor: '#F3F4F6', ink: '#1F3FD8', small: '#7A869E' },
    { id: 'terracotta-cream', label: 'Terracotta & cream', floor: '#C65A3A', ink: '#F6E7D2', small: '#5E2414' }
  ];

  var FX_ALL = { shadow: true, blur: true, focus: true, grain: false, vignette: true, texture: false };

  // ready looks: shown first; every field is a starting point the creator can change
  var LOOKS = [
    { id: 'original', label: 'Original', vibe: 'The reference: red words, a slow pull back.',
      palette: 'sage-red', font: 'condensed', layout: 'wall', entrance: 'slide', camera: 'pull', pace: 'smooth', ending: 'exit',
      fx: { shadow: true, blur: true, focus: true, grain: false, vignette: true, texture: false } },
    { id: 'noir', label: 'Noir', vibe: 'Black and white. Words fall like rain.',
      palette: 'noir', font: 'stencil', layout: 'stripes', entrance: 'drop', camera: 'crane', pace: 'dramatic', ending: 'dive',
      fx: { shadow: true, blur: true, focus: true, grain: true, vignette: true, texture: false } },
    { id: 'editorial', label: 'Editorial', vibe: 'A magazine cover lying at your feet.',
      palette: 'cream-navy', font: 'serif', layout: 'poster', entrance: 'wipe', camera: 'push', pace: 'smooth', ending: 'cut',
      fx: { shadow: true, blur: false, focus: false, grain: false, vignette: true, texture: true } },
    { id: 'terminal', label: 'Terminal', vibe: 'Typed out like code while the floor spins.',
      palette: 'graphite-lime', font: 'mono', layout: 'wall', entrance: 'type', camera: 'orbit', pace: 'fast', ending: 'exit',
      fx: { shadow: true, blur: false, focus: true, grain: true, vignette: true, texture: false } },
    { id: 'loud', label: 'Loud', vibe: 'One giant word. Everything pops.',
      palette: 'yellow-black', font: 'geo', layout: 'giant', entrance: 'pop', camera: 'push', pace: 'fast', ending: 'dive',
      fx: { shadow: true, blur: true, focus: false, grain: false, vignette: false, texture: false } },
    { id: 'sketch', label: 'Sketchbook', vibe: 'Hand-drawn words flip up around you.',
      palette: 'pink-wine', font: 'hand', layout: 'wall', entrance: 'rise', camera: 'still', pace: 'smooth', ending: 'sink',
      fx: { shadow: true, blur: true, focus: true, grain: true, vignette: true, texture: true } }
  ];

  var OPTIONS = {
    layout: [
      { id: 'wall',    label: 'Wall',       hint: 'Rows of words everywhere, like the reference.' },
      { id: 'giant',   label: 'Giant word', hint: 'One huge word under your feet.' },
      { id: 'stripes', label: 'Stripes',    hint: 'Bands of words with floor between them.' },
      { id: 'poster',  label: 'Poster',     hint: 'A stacked block, like a magazine cover.' }
    ],
    entrance: [
      { id: 'slide', label: 'Slide & bounce', hint: 'Rows fly in from the side and settle.' },
      { id: 'drop',  label: 'Drop',           hint: 'Words fall onto the floor.' },
      { id: 'rise',  label: 'Flip up',        hint: 'Rows stand up from the floor.' },
      { id: 'type',  label: 'Typewriter',     hint: 'Word by word, like typing.' },
      { id: 'pop',   label: 'Pop',            hint: 'Each word pops in with a bounce.' },
      { id: 'wipe',  label: 'Wipe',           hint: 'A clean reveal, editorial style.' }
    ],
    camera: [
      { id: 'pull',  label: 'Pull back & tilt', hint: 'The reference move.' },
      { id: 'crane', label: 'Rise',             hint: 'Starts at your feet and climbs.' },
      { id: 'orbit', label: 'Orbit',            hint: 'The floor turns around you.' },
      { id: 'push',  label: 'Push in',          hint: 'Ends closer to you.' },
      { id: 'still', label: 'Locked',           hint: 'Only the words move.' }
    ],
    pace: [
      { id: 'fast',     label: 'Fast',          hint: 'Snappy, everything lands quickly.' },
      { id: 'smooth',   label: 'Smooth',        hint: 'The reference rhythm.' },
      { id: 'dramatic', label: 'Dramatic',      hint: 'Slower, heavier landings.' },
      { id: 'speech',   label: 'On your voice', hint: 'Each word lands when you say it.' }
    ],
    ending: [
      { id: 'cut',  label: 'Hard cut',      hint: 'Ends clean, ready for your next clip.' },
      { id: 'exit', label: 'Words fly off', hint: 'The floor clears, you stay.' },
      { id: 'dive', label: 'Dive in',       hint: 'The camera dives into you, flash to white.' },
      { id: 'sink', label: 'Floor drops',   hint: 'The floor falls away under you.' }
    ],
    fx: [
      { id: 'shadow',   label: 'Shadow' },
      { id: 'blur',     label: 'Motion blur' },
      { id: 'focus',    label: 'Depth of field' },
      { id: 'grain',    label: 'Film grain' },
      { id: 'vignette', label: 'Vignette' },
      { id: 'texture',  label: 'Floor texture' }
    ]
  };

  // hooks Claude suggests for a take (the skill writes take-specific ones into take.json "suggestions")
  var SUGGESTIONS = [
    'Words on the floor, made for free',
    'You don’t need After Effects for this',
    'Steal this 3D text trick',
    'This intro took zero editing'
  ];

  function lookSettings(lookId, text) {
    var l = LOOKS.filter(function (x) { return x.id === lookId; })[0] || LOOKS[0];
    var p = PALETTES.filter(function (x) { return x.id === l.palette; })[0];
    return {
      look: l.id,
      text: text || { source: 'suggested', phrase: SUGGESTIONS[0], hero: 'TEXT', small: '' },
      palette: { id: p.id, floor: p.floor, ink: p.ink, small: p.small },
      font: l.font, layout: l.layout, entrance: l.entrance, camera: l.camera, pace: l.pace, ending: l.ending,
      fx: JSON.parse(JSON.stringify(l.fx)),
      sound: { voice: true, sfx: true }
    };
  }

  root.FT_DATA = { FONTS: FONTS, PALETTES: PALETTES, LOOKS: LOOKS, OPTIONS: OPTIONS, SUGGESTIONS: SUGGESTIONS,
                   FX_ALL: FX_ALL, lookSettings: lookSettings };
})(typeof window !== 'undefined' ? window : this);
