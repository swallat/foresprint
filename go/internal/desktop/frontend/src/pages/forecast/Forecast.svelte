<script lang="ts">
  import type { PageProps } from '../../lib/routes';
  import Placeholder from '../../lib/ui/Placeholder.svelte';

  let { params }: PageProps = $props();
  void params;
</script>

<Placeholder title="Forecast" pkg="P4 Forecast" spec="flows.md F6, decisions 18, 19, 24" />
