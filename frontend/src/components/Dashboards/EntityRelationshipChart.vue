<script setup lang="ts">
import { computed, useId } from "vue";

import type { DiagramEntity, DiagramRelation } from "@/types/dashboard";
import { entityLayout, relationPath } from "@/components/Dashboards/diagramLayout";

const markerId = `entity-arrow-${useId().replace(/:/g, "")}`;
const props = defineProps<{ entities: DiagramEntity[]; relations: DiagramRelation[] }>();
const entities = computed(() => entityLayout(props.entities, props.relations));
const paths = computed(() => props.relations.map((relation) => relationPath(relation, entities.value)).filter((path) => path !== null));
const width = computed((): number => Math.max(360, ...entities.value.map((entity) => entity.x + 350)));
const height = computed((): number => Math.max(160, ...entities.value.map((entity) => entity.y + entity.height + 52)));
</script>

<template>
  <div
    class="h-full w-full overflow-auto"
    tabindex="0"
    aria-label="Entity relationship diagram, scroll to explore tables"
  >
    <svg
      :viewBox="`0 0 ${width} ${height}`"
      :style="{ maxWidth: `${width}px` }"
      class="h-auto w-full min-w-[320px] text-foreground"
      role="img"
      aria-label="Database entities, fields and relationships"
    >
      <defs>
        <marker
          :id="markerId"
          markerWidth="6"
          markerHeight="6"
          refX="5"
          refY="3"
          orient="auto"
        >
          <path
            d="M 0 0 L 6 3 L 0 6 Z"
            fill="currentColor"
            class="text-primary"
          />
        </marker>
      </defs>
      <g
        v-for="(path, index) in paths"
        :key="index"
      >
        <path
          :d="path.path"
          :marker-end="`url(#${markerId})`"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          class="text-primary"
        />
        <text
          :x="path.x"
          :y="path.y"
          text-anchor="middle"
          fill="currentColor"
          class="text-[15px] text-muted-foreground"
          paint-order="stroke"
          stroke="hsl(var(--background))"
          stroke-width="4"
        >
          {{ path.label }}
        </text>
      </g>
      <g
        v-for="entity in entities"
        :key="entity.id"
        :transform="`translate(${entity.x}, ${entity.y})`"
      >
        <title>{{ entity.label }}: {{ entity.fields?.map(field => `${field.name} ${field.type || ''} ${field.key || ''}`).join(', ') }}</title>
        <rect
          width="260"
          :height="entity.height"
          rx="8"
          fill="hsl(var(--card))"
          stroke="hsl(var(--border))"
        />
        <rect
          x="1"
          y="1"
          width="258"
          height="36"
          rx="7"
          fill="currentColor"
          class="text-primary/10"
        />
        <text
          x="14"
          y="24"
          fill="currentColor"
          class="text-xl font-semibold"
        >{{ entity.label.length > 23 ? entity.label.slice(0, 22) + '…' : entity.label }}</text>
        <g
          v-for="(field, index) in entity.fields"
          :key="field.name"
        >
          <text
            x="12"
            :y="62 + index * 28"
            fill="currentColor"
            class="text-sm font-semibold text-primary"
          >{{ field.key }}</text>
          <text
            x="52"
            :y="62 + index * 28"
            fill="currentColor"
            class="text-base"
          >{{ field.name.length > 13 ? field.name.slice(0, 10) + '…' : field.name }}</text>
          <text
            x="248"
            :y="62 + index * 28"
            text-anchor="end"
            fill="currentColor"
            class="text-sm text-muted-foreground"
          >{{ (field.type || '').slice(0, 10) }}</text>
        </g>
      </g>
    </svg>
  </div>
</template>
