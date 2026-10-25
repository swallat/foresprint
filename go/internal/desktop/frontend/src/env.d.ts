/// <reference types="svelte" />
/// <reference types="vite/client" />

declare module '@material-symbols/svg-400/outlined/*.svg?raw' {
  const svg: string;
  export default svg;
}

declare module '*.txt?raw' {
  const text: string;
  export default text;
}
