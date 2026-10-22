<script lang="ts">
  import type { PageProps } from '../../lib/routes';
  import Placeholder from '../../lib/ui/Placeholder.svelte';

  let { params }: PageProps = $props();
  void params;
</script>

<Placeholder title="Plan" pkg="P3 Vorplanen und Planen" spec="flows.md F4, decisions 6, 7, 10" />
