// «Макс» — голубь, который помогает разобраться в ЖКХ.
// The 11 poses were cropped from `mascot.svg` (a layered sprite sheet) into
// individual images. BASE_URL keeps them working under the deployed Pages sub-path.
const base = import.meta.env.BASE_URL
const pose = (n: number) => `${base}mascot/max-${String(n).padStart(2, '0')}.png`

export const mascotPoses = Array.from({ length: 11 }, (_, i) => pose(i + 1))

export const mascot = {
  // 01 wink · 02 thinking "?" · 03 full mascot with mail bag · 04 thoughtful · 05 wink
  // 06 worried · 07 sunglasses · 08 reading the news · 09 greeting · 10 at a laptop · 11 megaphone
  logo: pose(1),
  hero: pose(3),
  tip: pose(2),
  success: pose(1),
  calm: pose(7),
  attention: pose(6),
  sad: pose(4),
  report: pose(8),
  greeting: pose(9),
  work: pose(10),
  announce: pose(11),
  name: 'Макс',
}
