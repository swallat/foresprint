<script lang="ts">
  import { iconSvg, type IconName } from './icons';

  interface Props {
    name: IconName;
    size?: number;
  }
  let { name, size = 20 }: Props = $props();
</script>

<span class="ic" style:--ic={`${size}px`} aria-hidden="true">{@html iconSvg(name)}</span>

<style>
  .ic {
    display: inline-flex;
    width: var(--ic);
    height: var(--ic);
    flex: none;
    vertical-align: middle;
  }
  .ic :global(svg) {
    width: 100%;
    height: 100%;
    fill: currentColor;
  }
</style>
