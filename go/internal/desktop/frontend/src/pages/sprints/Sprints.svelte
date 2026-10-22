<script lang="ts">
  import type { PageProps } from '../../lib/routes';
  import Placeholder from '../../lib/ui/Placeholder.svelte';

  let { params }: PageProps = $props();
  void params;
</script>

<Placeholder title="Sprint overview" pkg="P2 Sprint-Arbeitsraum" spec="flows.md section 5 (Sprints)" />
