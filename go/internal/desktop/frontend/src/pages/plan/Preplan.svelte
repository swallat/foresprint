<script lang="ts">
  import type { PageProps } from '../../lib/routes';
  import Placeholder from '../../lib/ui/Placeholder.svelte';

  let { params }: PageProps = $props();
  void params;
</script>

<Placeholder title="Pre-plan" pkg="P3 Vorplanen und Planen" spec="flows.md F3, decisions 14, 17, 20" />
