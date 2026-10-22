<script lang="ts">
  import type { PageProps } from '../../lib/routes';
  import Placeholder from '../../lib/ui/Placeholder.svelte';

  let { params }: PageProps = $props();
  void params;
</script>

<Placeholder title="Tickets and tracker" pkg="P8 Einstellungen und Tracker" spec="flows.md decisions 15, 21" />
