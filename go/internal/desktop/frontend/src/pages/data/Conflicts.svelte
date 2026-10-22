<script lang="ts">
  import type { PageProps } from '../../lib/routes';
  import Placeholder from '../../lib/ui/Placeholder.svelte';

  let { params }: PageProps = $props();
  void params;
</script>

<Placeholder title="Conflicts" pkg="P7" spec="flows.md D3" />
