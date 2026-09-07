<script lang="ts">
  // Filters the server-rendered #roster table in place. The table works
  // without this island; it only adds the text and facet filters, and reads
  // ?chamber= from the URL so links from the home page land pre-filtered.
  interface Props {
    parties: string[];
  }
  const { parties }: Props = $props();

  let query = $state("");
  let chamber = $state<"" | "house" | "senate">("");
  let party = $state("");
  let shown = $state<number | null>(null);

  $effect(() => {
    const params = new URLSearchParams(location.search);
    const c = params.get("chamber");
    if (c === "house" || c === "senate") chamber = c;
  });

  $effect(() => {
    const rows = document.querySelectorAll<HTMLTableRowElement>("#roster tbody tr");
    const q = query.trim().toLowerCase();
    let visible = 0;
    for (const row of rows) {
      const ok =
        (!chamber || row.dataset.chamber === chamber) &&
        (!party || row.dataset.party === party) &&
        (!q || (row.dataset.search ?? "").includes(q));
      row.hidden = !ok;
      if (ok) visible++;
    }
    shown = visible;
    const empty = document.getElementById("roster-empty");
    if (empty) empty.hidden = visible > 0;
  });
</script>

<form class="filter" role="search" onsubmit={(e) => e.preventDefault()}>
  <label>
    <span>Find</span>
    <input
      type="search"
      bind:value={query}
      placeholder="Name, party, electorate…"
      autocomplete="off"
    />
  </label>
  <fieldset>
    <legend>Chamber</legend>
    <label><input type="radio" bind:group={chamber} value="" /> Both</label>
    <label><input type="radio" bind:group={chamber} value="house" /> House</label>
    <label><input type="radio" bind:group={chamber} value="senate" /> Senate</label>
  </fieldset>
  <label>
    <span>Party</span>
    <select bind:value={party}>
      <option value="">All parties</option>
      {#each parties as p (p)}
        <option value={p}>{p}</option>
      {/each}
    </select>
  </label>
  <output aria-live="polite" class="muted">{shown === null ? "" : `${shown} shown`}</output>
</form>

<style>
  .filter {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: var(--space-3) var(--space-5);
    margin-block: var(--space-5);
    padding-block: var(--space-4);
    border-block: 1px solid var(--rule);
  }

  label > span,
  legend {
    display: block;
    font-size: var(--text-sm);
    color: var(--muted);
    margin-bottom: var(--space-1);
    padding: 0;
  }

  fieldset {
    border: 0;
    margin: 0;
    padding: 0;
    display: flex;
    gap: var(--space-3);
    align-items: end;
  }

  fieldset legend {
    float: left;
    width: 100%;
  }

  fieldset label {
    display: inline-flex;
    gap: var(--space-1);
    align-items: center;
  }

  input[type="search"],
  select {
    font: inherit;
    color: inherit;
    background: var(--bg);
    border: 1px solid var(--rule-strong);
    border-radius: var(--radius);
    padding: var(--space-2) var(--space-3);
    min-width: 16rem;
  }

  output {
    font-size: var(--text-sm);
    margin-left: auto;
  }
</style>
