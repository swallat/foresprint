<script lang="ts">
  import type { PageProps } from '../../lib/routes';
  import Placeholder from '../../lib/ui/Placeholder.svelte';

  let { params }: PageProps = $props();
  void params;
</script>

<Placeholder title="People and absences" pkg="P5" spec="flows.md decisions 1, 11, 16, 23" />
