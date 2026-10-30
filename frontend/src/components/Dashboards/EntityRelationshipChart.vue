<script setup lang="ts">
import { computed, useId } from "vue";

import type { DiagramEntity, DiagramRelation } from "@/types/dashboard";
import { entityScene, truncateDiagramText } from "@/components/Dashboards/diagramLayout";
import { useDiagramViewport } from "@/components/Dashboards/useDiagramViewport";

const markerId = `entity-arrow-${useId().replace(/:/g, "")}`;
const props = defineProps<{ entities: DiagramEntity[]; relations: DiagramRelation[] }>();
const { container, size } = useDiagramViewport();
const scene = computed(() => entityScene(props.entities, props.relations, size.value));
const viewBox = computed((): string => {
  const width = Math.max(scene.value.width, size.value.width / 1.2);
  const height = Math.max(scene.value.height, size.value.height / 1.2);
  return `${-(width - scene.value.width) / 2} ${-(height - scene.value.height) / 2} ${width} ${height}`;
});
</script>

<template>
  <div
    ref="container"
    class="h-full min-h-0 w-full min-w-0 overflow-hidden"
    aria-label="Entity relationship diagram"
  >
    <svg
      :viewBox="viewBox"
      class="block h-full w-full text-foreground"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="Database entities, fields and relationships"
    >
      <defs>
        <marker
          :id="markerId"
          markerWidth="6"
          markerHeight="6"
          refX="6"
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
      <path
        v-for="(path, index) in scene.relations"
        :key="index"
        :d="path.path"
        :marker-end="`url(#${markerId})`"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        class="text-primary"
      />
      <g
        v-for="entity in scene.entities"
        :key="entity.id"
        data-diagram-entity
        :transform="`translate(${entity.x}, ${entity.y})`"
      >
        <title>{{ entity.label }}: {{ entity.fields?.map(field => `${field.name} ${field.type || ''} ${field.key || ''}`).join(', ') }}</title>
        <rect
          :width="entity.width"
          :height="entity.height"
          rx="8"
          fill="hsl(var(--card))"
          stroke="hsl(var(--border))"
        />
        <rect
          x="1"
          y="1"
          :width="entity.width - 2"
          height="35"
          rx="7"
          fill="currentColor"
          class="text-primary/10"
        />
        <text
          x="12"
          y="24"
          fill="currentColor"
          class="font-semibold"
          :font-size="entity.width < 220 ? 14 : 15"
        >{{ truncateDiagramText(entity.label, entity.width - 24, 15) }}</text>
        <g
          v-for="(field, index) in entity.fields"
          :key="field.name"
        >
          <title>{{ field.name }} {{ field.type }} {{ field.key }}</title>
          <text
            x="12"
            :y="52 + index * 26"
            fill="currentColor"
            class="font-semibold text-primary"
            :font-size="entity.width < 220 ? 10 : 12"
          >{{ field.key }}</text>
          <text
            :x="entity.width < 220 ? 36 : 48"
            :y="52 + index * 26"
            fill="currentColor"
            :font-size="entity.width < 220 ? 12 : 14"
          >{{ truncateDiagramText(field.name, entity.width - (entity.width < 220 ? 98 : 140), entity.width < 220 ? 12 : 14) }}</text>
          <text
            :x="entity.width - 12"
            :y="52 + index * 26"
            text-anchor="end"
            fill="currentColor"
            class="text-muted-foreground"
            :font-size="entity.width < 220 ? 10 : 12"
          >{{ truncateDiagramText(field.type || '', entity.width < 220 ? 48 : 66, entity.width < 220 ? 10 : 12) }}</text>
        </g>
      </g>
      <!-- Captions render above the cards, in the reserved gutters, with bounded wrapping. -->
      <g
        v-for="(path, index) in scene.relations"
        :key="index"
        data-diagram-relation-label
      >
        <title>{{ path.label }}</title>
        <rect
          :x="path.x - path.labelWidth / 2"
          :y="path.y - path.labelHeight / 2"
          :width="path.labelWidth"
          :height="path.labelHeight"
          rx="4"
          fill="hsl(var(--card))"
        />
        <text
          :x="path.x"
          text-anchor="middle"
          fill="currentColor"
          class="text-xs text-muted-foreground"
        >
          <tspan
            v-for="(line, lineIndex) in path.lines"
            :key="lineIndex"
            :x="path.x"
            :y="path.y - path.labelHeight / 2 + 14 + lineIndex * 14"
          >{{ line }}</tspan>
        </text>
      </g>
    </svg>
  </div>
</template>
