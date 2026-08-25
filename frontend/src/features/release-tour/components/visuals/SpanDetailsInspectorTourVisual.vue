<template>
  <div class="flex h-full w-full flex-col gap-1.5 overflow-hidden p-2">
    <div class="flex h-10 items-center gap-1 rounded border border-border bg-card px-1.5">
      <span class="h-2 w-1/4 rounded bg-emerald-500/60" />
      <span class="h-2 w-1/3 rounded bg-amber-500/60" />
      <span class="h-2 w-1/5 rounded bg-rose-500/70" />
    </div>
    <div class="flex min-h-0 flex-1 flex-col gap-1 rounded border border-primary/40 bg-primary/5 p-1.5">
      <div class="flex items-center justify-between text-[9px] font-semibold text-foreground">
        <span>Agent · failed</span>
        <span class="font-mono text-muted-foreground">1.8s</span>
      </div>
      <div class="grid grid-cols-4 gap-1 text-[8px] text-muted-foreground">
        <span>Status<br><b class="text-rose-500">Error</b></span>
        <span>Attempts<br><b class="text-foreground">2</b></span>
        <span>Trace<br><b class="text-primary">Open</b></span>
        <span>Wait<br><b class="text-foreground">None</b></span>
      </div>
      <div class="mt-auto rounded border border-border bg-card p-1 text-[8px] text-muted-foreground">
        Output <span class="text-foreground">{ result: {…} }</span>
      </div>
    </div>
  </div>
</template>
