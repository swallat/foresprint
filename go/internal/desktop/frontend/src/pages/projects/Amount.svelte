<script lang="ts">
  import { num } from './format';

  interface Props {
    value: number | null;
    /** An estimate (converted from points): the sign hangs to the left, so the digits of
     * estimates and entered values stay in line. */
    est?: boolean;
    digits?: number;
    /** In running text the sign stays in the line instead of hanging to the left. */
    inline?: boolean;
  }
  let { value, est = false, digits = 1, inline = false }: Props = $props();
</script>

<span class="amt data" class:est={est && value !== null && !inline}>{est && inline && value !== null ? '≈ ' : ''}{num(value, digits)}</span>

<style>
  .amt {
    position: relative;
    white-space: nowrap;
  }
  .amt.est::before {
    content: '≈';
    position: absolute;
    right: 100%;
    margin-right: 2px;
    color: var(--text-muted);
  }
</style>
