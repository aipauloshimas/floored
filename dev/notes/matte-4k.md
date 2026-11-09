# Cutout at 4K: downsample choice (Task 7, Step 5)

Date: 2026-11-09. Reviewed by the lead on 1:1 crops.

**Choice: `--downsample 0.375` at 4K** (`downsample_for(3840)`), the same effective model input as a 1080p take at 0.75.

## What was looked at

- Input: the first 0.5 s (12 frames) of the sample take, upscaled to 2160×3840 with lanczos. It is not native 4K, so
  fine detail is limited by the 1080 source; a native 4K phone take (gate G1) should repeat this look.
- Output composited over a light floor (#e8e4dc) and a dark floor (#1c1c1e). 1:1 crops of the hands (clasped in
  front of the body, with floor showing between hands and jeans) and of the sleeve silhouette against the floor,
  frames 0, 6 and 11, at 0.375 and at 0.5.

## Findings

| | 0.375 | 0.5 |
|---|---|---|
| Hands and fingers | whole, no holes, fingers separate | same |
| Silhouette (sleeve, jeans) | smooth, no chewing | same, contour marginally steadier at the jeans corner |
| Rim on the dark floor | thin light rim (1–2 px at 4K) | same |
| Time for 12 frames (CPU) | 115–134 s | 183 s |

0.5 is not visibly better than 0.375 on this footage and costs about 40 % more time, so 0.375 stays.

## Observation (not 4K-specific)

On a dark floor the cutout edge shows a thin light rim: the edge pixels keep the colour of the original light floor
(colour spill), at 1080 as at 4K. The earlier build has the same rim. If it shows on the dark looks (Noir, Terminal) in
real takes, a later pass could take the edge colour from RVM's own foreground output instead of the source pixels.
