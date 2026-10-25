<script setup lang="ts">
import { computed } from "vue";
import { Bot, Mic, MicOff, Type } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only, styled after the real canvas. 0: two people on one canvas ·
// 1: Ana adds a node, Ben sees it · 2: Ben follows Ana · 3: Ana talks with the mic on.
const step = useCycleStep(4, 1800);

const ANA = "hsl(var(--primary))";
const BEN = "hsl(var(--success))";
const DOTS = "radial-gradient(hsl(var(--muted-foreground) / 0.35) 1px, transparent 1px)";

const nodeVisible = computed<boolean>(() => step.value >= 1);
const following = computed<boolean>(() => step.value === 2);
const talking = computed<boolean>(() => step.value === 3);
const anaCursor = computed<Record<string, string>>(() =>
  step.value === 0 ? { left: "30%", top: "70%" } : { left: "70%", top: "44%" },
);
const benCursor = computed<Record<string, string>>(() =>
  step.value >= 2 ? { left: "73%", top: "56%" } : { left: "80%", top: "76%" },
);
const caption = computed<string>(() => {
  if (step.value === 0) return "Everyone on the canvas, top left";
  if (step.value === 1) return "Edits show up for everyone";
  if (step.value === 2) return "Click an avatar to follow";
  return "Turn the mic on to talk";
});

function ring(color: string): Record<string, string> {
  return { boxShadow: `0 0 0 1.5px hsl(var(--background)), 0 0 0 3px ${color}` };
}

function node(token: string): Record<string, string> {
  return { borderColor: `hsl(var(--${token}) / 0.6)` };
}
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2 overflow-hidden rounded-lg bg-card p-3">
    <div
      class="relative min-h-0 flex-1 overflow-hidden rounded-md border-2 bg-background transition-colors duration-500"
      :style="{
        borderColor: following ? ANA : 'transparent',
        backgroundImage: DOTS,
        backgroundSize: '10px 10px',
      }"
    >
      <div class="absolute left-2 top-2 flex items-center gap-1.5">
        <div class="flex -space-x-0.5">
          <span
            class="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-[8px] font-semibold"
            :class="talking ? 'animate-pulse' : ''"
            :style="ring(ANA)"
          >A</span>
          <span
            class="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-[8px] font-semibold"
            :style="ring(BEN)"
          >B</span>
        </div>
        <span
          class="flex h-5 w-5 items-center justify-center rounded-full border transition-colors duration-500"
          :class="talking ? 'border-primary bg-primary/15 text-primary' : 'border-border bg-card text-muted-foreground'"
        >
          <Mic
            v-if="talking"
            class="h-2.5 w-2.5"
          />
          <MicOff
            v-else
            class="h-2.5 w-2.5"
          />
        </span>
      </div>
      <span
        v-if="following"
        class="absolute left-1/2 top-2 -translate-x-1/2 whitespace-nowrap rounded-full px-2 py-0.5 text-[8px] font-medium text-white"
        :style="{ backgroundColor: ANA }"
      >Following Ana · Esc to stop</span>

      <svg
        class="absolute inset-0 h-full w-full"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path
          d="M 36 52 C 46 52, 46 34, 56 34"
          fill="none"
          stroke="hsl(var(--muted-foreground))"
          stroke-width="0.8"
          stroke-dasharray="2 2"
          vector-effect="non-scaling-stroke"
          class="transition-opacity duration-500"
          :class="nodeVisible ? 'opacity-70' : 'opacity-0'"
        />
      </svg>

      <div
        class="absolute left-[8%] top-[42%] flex items-center gap-1.5 overflow-hidden rounded-lg border bg-card px-1.5 pb-1 pt-1.5"
        :style="node('node-input')"
      >
        <span
          class="absolute inset-x-0 top-0 h-[2px]"
          style="background-color: hsl(var(--node-input))"
        />
        <span class="flex h-4 w-4 items-center justify-center rounded bg-node-input/10 text-node-input">
          <Type class="h-2.5 w-2.5" />
        </span>
        <span class="text-[9px] font-semibold">userInput</span>
      </div>
      <div
        class="absolute left-[56%] top-[24%] flex items-center gap-1.5 overflow-hidden rounded-lg border bg-card px-1.5 pb-1 pt-1.5 transition-all duration-500"
        :class="nodeVisible ? 'scale-100 opacity-100' : 'scale-75 opacity-0'"
        :style="node('node-agent')"
      >
        <span
          class="absolute inset-x-0 top-0 h-[2px]"
          style="background-color: hsl(var(--node-agent))"
        />
        <span class="flex h-4 w-4 items-center justify-center rounded bg-node-agent/10 text-node-agent">
          <Bot class="h-2.5 w-2.5" />
        </span>
        <span class="text-[9px] font-semibold">replyAgent</span>
      </div>

      <div
        v-for="cursor in [{ name: 'Ana', color: ANA, at: anaCursor }, { name: 'Ben', color: BEN, at: benCursor }]"
        :key="cursor.name"
        class="absolute flex items-start transition-all duration-700 ease-out"
        :style="cursor.at"
      >
        <svg
          width="10"
          height="11"
          viewBox="0 0 16 18"
          aria-hidden="true"
        >
          <path
            d="M1 1 L15 7.5 L8.5 9.5 L6 16.5 Z"
            :fill="cursor.color"
            stroke="white"
            stroke-width="1.25"
            stroke-linejoin="round"
          />
        </svg>
        <span
          class="ml-0.5 mt-2 rounded px-1 text-[7px] font-medium leading-tight text-white"
          :style="{ backgroundColor: cursor.color }"
        >{{ cursor.name }}</span>
      </div>
    </div>
    <p class="text-center text-[10px] leading-none text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
