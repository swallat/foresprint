<script lang="ts">
  import type { PageProps } from '../../lib/routes';
  import Placeholder from '../../lib/ui/Placeholder.svelte';

  let { params }: PageProps = $props();
  void params;
</script>

<Placeholder title="Prepare" pkg="P2 Sprint-Arbeitsraum" spec="flows.md F3, decisions 1 and 23" />
