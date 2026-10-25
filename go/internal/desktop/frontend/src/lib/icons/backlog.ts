// Icons of the area backlog. To use an icon that is not in core.ts or another area file, add one
// import line (the file name is the icon name in
// node_modules/@material-symbols/svg-400/outlined) and one entry:
//
//   import i_add from '@material-symbols/svg-400/outlined/add.svg?raw';
//   const icons = { add: i_add } as const;

import i_vertical_split from '@material-symbols/svg-400/outlined/vertical_split.svg?raw';
import i_splitscreen from '@material-symbols/svg-400/outlined/splitscreen.svg?raw';

const icons = { vertical_split: i_vertical_split, splitscreen: i_splitscreen } as const;

export default icons;
