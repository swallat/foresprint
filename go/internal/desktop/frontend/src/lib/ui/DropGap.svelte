<script lang="ts">
  // The placeholder every drag-and-drop list shows where the dragged item will land: a gap
  // as high as the dragged row, outlined in the accent. It sits inside the drop target's own
  // element, so the pointer over the gap still counts as over that target (no flicker when
  // the list moves apart). Purely visual; the lists keep their keyboard ways.
  let { height = 40 }: { height?: number } = $props();
</script>

<div class="drop-gap" aria-hidden="true" style:--gap-h={`${Math.max(28, Math.min(height, 96))}px`}></div>
