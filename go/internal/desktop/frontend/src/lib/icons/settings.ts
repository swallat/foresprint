// Icons of the area settings. To use an icon that is not in core.ts or another area file, add one
// import line (the file name is the icon name in
// node_modules/@material-symbols/svg-400/outlined) and one entry:
//
//   import i_add from '@material-symbols/svg-400/outlined/add.svg?raw';
//   const icons = { add: i_add } as const;

import i_open_in_browser from '@material-symbols/svg-400/outlined/open_in_browser.svg?raw';
import i_stop_circle from '@material-symbols/svg-400/outlined/stop_circle.svg?raw';

const icons = { open_in_browser: i_open_in_browser, stop_circle: i_stop_circle } as const;

export default icons;
