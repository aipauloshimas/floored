"""Every number the measuring and the take check decide with, in one place.

Tuned on 2026-11-09 on AI-generated takes (the look most creators will bring) plus the shipped sample: change them here
and nowhere else. Pixel values are for a 1080-wide picture (the pipeline measures the 1080 proxy, also for a 4K take).
"""

# --- person size on the floor ---------------------------------------------------------------------------------------
K0_SCALE = 0.78                  # k0 = K0_SCALE * K0_REF_HEIGHT / the person's height in px
K0_REF_HEIGHT = 790

# --- the take check: what is worth a warning -------------------------------------------------------------------------
SHORT_S = 3.0                    # shorter than this: too short
LONG_S = 8.0                     # longer than this: too long (still fine up to MAX_S)
MAX_S = 10.0                     # the most a take may be
MAX_S_GRACE = 0.25               # a clip is refused only above MAX_S + this (a phone's "10 s" clip reads 10.03 s)
LOWRES_H = 1280                  # a picture shorter than this (px) is low resolution
ASPECT_TOL = 0.02                # how far width / height may be from 9:16 before it is not 9:16
MOVED_PX = 60                    # the feet wander further than this (px at 1080 wide, scaled for other widths). Planted
                                 # feet measured up to ~50 (light shoes fading into a dark floor); a walk ~220
EDGE_PX = 2                      # a person within this many px of the picture's edge touches it
PEOPLE_RATIO = 0.15              # a second shape this big (share of the biggest shape's area) is another person
PEOPLE_SHARE = 0.5               # ...seen in at least this share of the frames
LEGS_RATIO = 0.85                # the bottom of the cutout is this wide or wider, as a share of the shoulders: it was cut
                                 # at the hips, the legs are lost (seen when filmed almost straight down; kept 0.34-0.66)
NOPERSON_AREA = 0.01             # the person fills less than this share of the picture (median frame): nobody is there

# --- finding the person and the feet in one frame --------------------------------------------------------------------
ALPHA_SOFT = 16                  # alpha above this counts as "something is there" (stray bits are dropped from this mask)
ALPHA_SOLID = 128                # alpha above this counts as the person's body
MIN_PERSON_PX = 3000             # fewer solid pixels than this in a frame: nobody there
BLOB_CELL = 8                    # the grid (px) the biggest-shape search runs on
SHOE_BAND_PX = 140               # the feet are looked for in the bottom this many px of the silhouette (260 let a hand at
                                 # hip height split from the legs and pull the feet to it; under 140 the sample breaks)
SHOE_GAP_PX = 8                  # a gap wider than this between columns of the bottom band separates the two shoes
SOLE_ROWS = 6                    # the sole is the lowest this many rows of a shoe

# --- measuring the whole clip ----------------------------------------------------------------------------------------
MIN_GOOD_SHARE = 0.3             # a person must be found in at least this share of the frames (and 3 frames)
MIN_HEIGHT_PX = 150              # a person shorter than this (px) is not a person
AO_PAD_PX = 150                  # the contact shadow is this much wider than the distance between the shoes
DRIFT_LOW = 10                   # the feet's drift is the distance between their position at this percentile of the frames...
DRIFT_HIGH = 90                  # ...and at this one (so a glitch in under 10 % of the frames is ignored)
MIN_GOOD_FRAMES = 3              # a person must be found in at least this many frames
ONE_SHOE_SHARE = 0.3             # the distance between the shoes counts when both shoes were found in this share of frames
