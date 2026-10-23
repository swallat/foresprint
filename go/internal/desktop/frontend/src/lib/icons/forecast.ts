// Icons of the area forecast. To use an icon that is not in core.ts or another area file, add one
// import line (the file name is the icon name in
// node_modules/@material-symbols/svg-400/outlined) and one entry:
//
//   import i_add from '@material-symbols/svg-400/outlined/add.svg?raw';
//   const icons = { add: i_add } as const;

import i_keyboard_arrow_up from '@material-symbols/svg-400/outlined/keyboard_arrow_up.svg?raw';
import i_keyboard_arrow_down from '@material-symbols/svg-400/outlined/keyboard_arrow_down.svg?raw';

const icons = { keyboard_arrow_up: i_keyboard_arrow_up, keyboard_arrow_down: i_keyboard_arrow_down } as const;

export default icons;
