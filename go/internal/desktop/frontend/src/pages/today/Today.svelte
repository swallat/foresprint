<script lang="ts">
  import type { PageProps } from '../../lib/routes';
  import Placeholder from '../../lib/ui/Placeholder.svelte';

  let { params }: PageProps = $props();
  void params;
</script>

<Placeholder title="Today" pkg="P9 Start und Hilfe" spec="flows.md section 5 (Today), F1" />
