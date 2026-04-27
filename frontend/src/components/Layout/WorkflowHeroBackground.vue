<script setup lang="ts">
// WorkflowHeroBackground — animated SVG graph that lives behind the workflow list header.
// Nodes, curved edges, and travelling dots illustrate the "workflow automation" concept
// without copying any external design asset. Colors are drawn from the existing CSS token set.
</script>

<template>
  <div
    class="workflow-hero-bg absolute inset-0 overflow-hidden pointer-events-none select-none"
    aria-hidden="true"
  >
    <svg
      viewBox="0 0 1400 480"
      preserveAspectRatio="xMidYMid slice"
      class="w-full h-full"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <!-- ── Arrowhead markers ── -->
        <marker
          id="wfbg-arrow-main"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="5"
          markerHeight="5"
          orient="auto-start-reverse"
        >
          <path
            d="M 0 1.5 L 9 5 L 0 8.5 Z"
            class="arrow-main"
          />
        </marker>
        <marker
          id="wfbg-arrow-branch"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="5"
          markerHeight="5"
          orient="auto-start-reverse"
        >
          <path
            d="M 0 1.5 L 9 5 L 0 8.5 Z"
            class="arrow-branch"
          />
        </marker>
        <marker
          id="wfbg-arrow-secondary"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="5"
          markerHeight="5"
          orient="auto-start-reverse"
        >
          <path
            d="M 0 1.5 L 9 5 L 0 8.5 Z"
            class="arrow-secondary"
          />
        </marker>
      </defs>

      <!-- ══════════════════════════════════════════════════
           EDGES  (drawn first so nodes render on top)
           ══════════════════════════════════════════════════ -->

      <!-- Primary flow ──────────────── -->
      <!-- E1: Webhook → HTTP Request -->
      <path
        class="edge edge-main"
        d="M 108 180 C 154 180 154 170 200 170"
        marker-end="url(#wfbg-arrow-main)"
      />
      <!-- E2: Webhook → LLM Model -->
      <path
        class="edge edge-main"
        d="M 108 180 C 154 180 154 240 200 240"
        marker-end="url(#wfbg-arrow-main)"
      />
      <!-- E3: HTTP Request → Condition -->
      <path
        class="edge edge-main"
        d="M 330 170 C 380 170 380 205 430 205"
        marker-end="url(#wfbg-arrow-main)"
      />
      <!-- E4: LLM Model → Condition -->
      <path
        class="edge edge-main"
        d="M 330 240 C 380 240 380 205 430 205"
        marker-end="url(#wfbg-arrow-main)"
      />
      <!-- E5: Condition → AI Agent (branch, dashed) -->
      <path
        class="edge edge-branch"
        d="M 550 205 C 600 205 600 150 650 150"
        marker-end="url(#wfbg-arrow-branch)"
      />
      <!-- E6: Condition → Set Variable (branch, dashed) -->
      <path
        class="edge edge-branch"
        d="M 550 205 C 600 205 600 270 650 270"
        marker-end="url(#wfbg-arrow-branch)"
      />
      <!-- E7: AI Agent → Merge -->
      <path
        class="edge edge-main"
        d="M 775 150 C 828 150 828 205 880 205"
        marker-end="url(#wfbg-arrow-main)"
      />
      <!-- E8: Set Variable → Merge -->
      <path
        class="edge edge-main"
        d="M 780 270 C 830 270 830 205 880 205"
        marker-end="url(#wfbg-arrow-main)"
      />
      <!-- E9: Merge → Respond -->
      <path
        class="edge edge-main"
        d="M 980 205 C 1015 205 1015 205 1050 205"
        marker-end="url(#wfbg-arrow-main)"
      />

      <!-- Secondary flow (bottom row) ──────────────── -->
      <!-- E10: Schedule → Transform -->
      <path
        class="edge edge-secondary"
        d="M 108 380 C 179 380 179 375 250 375"
        marker-end="url(#wfbg-arrow-secondary)"
      />
      <!-- E11: Transform → Filter -->
      <path
        class="edge edge-secondary"
        d="M 370 375 C 445 375 445 375 520 375"
        marker-end="url(#wfbg-arrow-secondary)"
      />
      <!-- E12: Filter → Send Email -->
      <path
        class="edge edge-secondary"
        d="M 640 375 C 720 375 720 375 800 375"
        marker-end="url(#wfbg-arrow-secondary)"
      />
      <!-- E13: Send Email → Notify -->
      <path
        class="edge edge-secondary"
        d="M 910 375 C 965 375 965 375 1020 375"
        marker-end="url(#wfbg-arrow-secondary)"
      />

      <!-- ══════════════════════════════════════════════════
           NODES
           ══════════════════════════════════════════════════ -->

      <!-- N1: Webhook (trigger circle) -->
      <g class="node node-trigger">
        <circle
          cx="80"
          cy="180"
          r="28"
          class="node-fill"
        />
        <circle
          cx="80"
          cy="180"
          r="28"
          class="node-ring"
        />
        <!-- lightning bolt -->
        <path
          d="M 83 167 L 76 181 L 82 181 L 77 194 L 84 180 L 78 180 Z"
          class="node-icon"
        />
        <!-- right handle -->
        <circle
          cx="108"
          cy="180"
          r="4"
          class="handle-right"
        />
        <text
          x="80"
          y="218"
          text-anchor="middle"
          class="node-type-label"
        >Webhook</text>
      </g>

      <!-- N2: HTTP Request (rect) -->
      <g class="node node-http">
        <rect
          x="200"
          y="150"
          width="130"
          height="40"
          rx="8"
          class="node-fill"
        />
        <rect
          x="200"
          y="150"
          width="130"
          height="40"
          rx="8"
          class="node-ring"
        />
        <rect
          x="200"
          y="150"
          width="4"
          height="40"
          rx="2"
          class="node-accent"
        />
        <circle
          cx="200"
          cy="170"
          r="4"
          class="handle-left"
        />
        <circle
          cx="330"
          cy="170"
          r="4"
          class="handle-right"
        />
        <text
          x="267"
          y="175"
          text-anchor="middle"
          class="node-label"
        >HTTP Request</text>
      </g>

      <!-- N3: LLM Model (rect) -->
      <g class="node node-llm">
        <rect
          x="200"
          y="220"
          width="130"
          height="40"
          rx="8"
          class="node-fill"
        />
        <rect
          x="200"
          y="220"
          width="130"
          height="40"
          rx="8"
          class="node-ring"
        />
        <rect
          x="200"
          y="220"
          width="4"
          height="40"
          rx="2"
          class="node-accent"
        />
        <circle
          cx="200"
          cy="240"
          r="4"
          class="handle-left"
        />
        <circle
          cx="330"
          cy="240"
          r="4"
          class="handle-right"
        />
        <text
          x="267"
          y="245"
          text-anchor="middle"
          class="node-label"
        >LLM Model</text>
      </g>

      <!-- N4: Condition (rect) -->
      <g class="node node-condition">
        <rect
          x="430"
          y="185"
          width="120"
          height="40"
          rx="8"
          class="node-fill"
        />
        <rect
          x="430"
          y="185"
          width="120"
          height="40"
          rx="8"
          class="node-ring"
        />
        <rect
          x="430"
          y="185"
          width="4"
          height="40"
          rx="2"
          class="node-accent"
        />
        <circle
          cx="430"
          cy="205"
          r="4"
          class="handle-left"
        />
        <circle
          cx="550"
          cy="205"
          r="4"
          class="handle-right"
        />
        <text
          x="492"
          y="210"
          text-anchor="middle"
          class="node-label"
        >Condition</text>
      </g>

      <!-- N5: AI Agent (rect) -->
      <g class="node node-agent">
        <rect
          x="650"
          y="130"
          width="125"
          height="40"
          rx="8"
          class="node-fill"
        />
        <rect
          x="650"
          y="130"
          width="125"
          height="40"
          rx="8"
          class="node-ring"
        />
        <rect
          x="650"
          y="130"
          width="4"
          height="40"
          rx="2"
          class="node-accent"
        />
        <circle
          cx="650"
          cy="150"
          r="4"
          class="handle-left"
        />
        <circle
          cx="775"
          cy="150"
          r="4"
          class="handle-right"
        />
        <text
          x="714"
          y="155"
          text-anchor="middle"
          class="node-label"
        >AI Agent</text>
      </g>

      <!-- N6: Set Variable (rect) -->
      <g class="node node-set">
        <rect
          x="650"
          y="250"
          width="130"
          height="40"
          rx="8"
          class="node-fill"
        />
        <rect
          x="650"
          y="250"
          width="130"
          height="40"
          rx="8"
          class="node-ring"
        />
        <rect
          x="650"
          y="250"
          width="4"
          height="40"
          rx="2"
          class="node-accent"
        />
        <circle
          cx="650"
          cy="270"
          r="4"
          class="handle-left"
        />
        <circle
          cx="780"
          cy="270"
          r="4"
          class="handle-right"
        />
        <text
          x="717"
          y="275"
          text-anchor="middle"
          class="node-label"
        >Set Variable</text>
      </g>

      <!-- N7: Merge (rect) -->
      <g class="node node-merge">
        <rect
          x="880"
          y="185"
          width="100"
          height="40"
          rx="8"
          class="node-fill"
        />
        <rect
          x="880"
          y="185"
          width="100"
          height="40"
          rx="8"
          class="node-ring"
        />
        <rect
          x="880"
          y="185"
          width="4"
          height="40"
          rx="2"
          class="node-accent"
        />
        <circle
          cx="880"
          cy="205"
          r="4"
          class="handle-left"
        />
        <circle
          cx="980"
          cy="205"
          r="4"
          class="handle-right"
        />
        <text
          x="932"
          y="210"
          text-anchor="middle"
          class="node-label"
        >Merge</text>
      </g>

      <!-- N8: Respond (rect) -->
      <g class="node node-output">
        <rect
          x="1050"
          y="185"
          width="110"
          height="40"
          rx="8"
          class="node-fill"
        />
        <rect
          x="1050"
          y="185"
          width="110"
          height="40"
          rx="8"
          class="node-ring"
        />
        <rect
          x="1050"
          y="185"
          width="4"
          height="40"
          rx="2"
          class="node-accent"
        />
        <circle
          cx="1050"
          cy="205"
          r="4"
          class="handle-left"
        />
        <text
          x="1107"
          y="210"
          text-anchor="middle"
          class="node-label"
        >Respond</text>
      </g>

      <!-- N9: Schedule (cron circle) -->
      <g class="node node-cron">
        <circle
          cx="80"
          cy="380"
          r="28"
          class="node-fill"
        />
        <circle
          cx="80"
          cy="380"
          r="28"
          class="node-ring"
        />
        <!-- clock face -->
        <circle
          cx="80"
          cy="380"
          r="11"
          fill="none"
          class="clock-ring"
        />
        <line
          x1="80"
          y1="380"
          x2="80"
          y2="371"
          class="clock-hand"
        />
        <line
          x1="80"
          y1="380"
          x2="88"
          y2="380"
          class="clock-hand"
        />
        <circle
          cx="108"
          cy="380"
          r="4"
          class="handle-right"
        />
        <text
          x="80"
          y="418"
          text-anchor="middle"
          class="node-type-label"
        >Schedule</text>
      </g>

      <!-- N10: Transform (rect) -->
      <g class="node node-set">
        <rect
          x="250"
          y="355"
          width="120"
          height="40"
          rx="8"
          class="node-fill"
        />
        <rect
          x="250"
          y="355"
          width="120"
          height="40"
          rx="8"
          class="node-ring"
        />
        <rect
          x="250"
          y="355"
          width="4"
          height="40"
          rx="2"
          class="node-accent"
        />
        <circle
          cx="250"
          cy="375"
          r="4"
          class="handle-left"
        />
        <circle
          cx="370"
          cy="375"
          r="4"
          class="handle-right"
        />
        <text
          x="312"
          y="380"
          text-anchor="middle"
          class="node-label"
        >Transform</text>
      </g>

      <!-- N11: Filter (rect) -->
      <g class="node node-condition">
        <rect
          x="520"
          y="355"
          width="120"
          height="40"
          rx="8"
          class="node-fill"
        />
        <rect
          x="520"
          y="355"
          width="120"
          height="40"
          rx="8"
          class="node-ring"
        />
        <rect
          x="520"
          y="355"
          width="4"
          height="40"
          rx="2"
          class="node-accent"
        />
        <circle
          cx="520"
          cy="375"
          r="4"
          class="handle-left"
        />
        <circle
          cx="640"
          cy="375"
          r="4"
          class="handle-right"
        />
        <text
          x="582"
          y="380"
          text-anchor="middle"
          class="node-label"
        >Filter</text>
      </g>

      <!-- N12: Send Email (rect) -->
      <g class="node node-email">
        <rect
          x="800"
          y="355"
          width="110"
          height="40"
          rx="8"
          class="node-fill"
        />
        <rect
          x="800"
          y="355"
          width="110"
          height="40"
          rx="8"
          class="node-ring"
        />
        <rect
          x="800"
          y="355"
          width="4"
          height="40"
          rx="2"
          class="node-accent"
        />
        <circle
          cx="800"
          cy="375"
          r="4"
          class="handle-left"
        />
        <circle
          cx="910"
          cy="375"
          r="4"
          class="handle-right"
        />
        <text
          x="857"
          y="380"
          text-anchor="middle"
          class="node-label"
        >Send Email</text>
      </g>

      <!-- N13: Notify (rect) -->
      <g class="node node-merge">
        <rect
          x="1020"
          y="355"
          width="100"
          height="40"
          rx="8"
          class="node-fill"
        />
        <rect
          x="1020"
          y="355"
          width="100"
          height="40"
          rx="8"
          class="node-ring"
        />
        <rect
          x="1020"
          y="355"
          width="4"
          height="40"
          rx="2"
          class="node-accent"
        />
        <circle
          cx="1020"
          cy="375"
          r="4"
          class="handle-left"
        />
        <text
          x="1072"
          y="380"
          text-anchor="middle"
          class="node-label"
        >Notify</text>
      </g>

      <!-- ══════════════════════════════════════════════════
           ANIMATED DOTS (data flowing along edges)
           ══════════════════════════════════════════════════ -->

      <!-- Dot on E1: Webhook → HTTP Request -->
      <circle
        r="3.5"
        class="dot dot-primary"
      >
        <animateMotion
          dur="4s"
          repeatCount="indefinite"
          path="M 108 180 C 154 180 154 170 200 170"
        />
      </circle>

      <!-- Dot on E3: HTTP → Condition -->
      <circle
        r="3.5"
        class="dot dot-primary"
      >
        <animateMotion
          dur="4.4s"
          repeatCount="indefinite"
          begin="0.4s"
          path="M 330 170 C 380 170 380 205 430 205"
        />
      </circle>

      <!-- Dot on E5: Condition → AI Agent -->
      <circle
        r="3.5"
        class="dot dot-agent"
      >
        <animateMotion
          dur="4.2s"
          repeatCount="indefinite"
          begin="0.8s"
          path="M 550 205 C 600 205 600 150 650 150"
        />
      </circle>

      <!-- Dot on E7: AI Agent → Merge -->
      <circle
        r="3.5"
        class="dot dot-agent"
      >
        <animateMotion
          dur="3.8s"
          repeatCount="indefinite"
          begin="1.2s"
          path="M 775 150 C 828 150 828 205 880 205"
        />
      </circle>

      <!-- Dot on E9: Merge → Respond (completion) -->
      <circle
        r="4"
        class="dot dot-output"
      >
        <animateMotion
          dur="3.6s"
          repeatCount="indefinite"
          begin="1.6s"
          path="M 980 205 C 1015 205 1015 205 1050 205"
        />
      </circle>

      <!-- Dot on E10: Schedule → Transform -->
      <circle
        r="3.5"
        class="dot dot-secondary"
      >
        <animateMotion
          dur="4.8s"
          repeatCount="indefinite"
          begin="0.6s"
          path="M 108 380 C 179 380 179 375 250 375"
        />
      </circle>

      <!-- Dot on E12: Filter → Send Email -->
      <circle
        r="3.5"
        class="dot dot-secondary"
      >
        <animateMotion
          dur="4.2s"
          repeatCount="indefinite"
          begin="1s"
          path="M 640 375 C 720 375 720 375 800 375"
        />
      </circle>
    </svg>
  </div>
</template>

<style scoped>
/* ── Container fade mask ── */
.workflow-hero-bg {
  opacity: 0.5;
  /* Only fade out toward the bottom so the graphic stays fully visible behind auth content */
  mask-image: linear-gradient(to bottom, black 0%, black 65%, transparent 100%);
  -webkit-mask-image: linear-gradient(to bottom, black 0%, black 65%, transparent 100%);
}

.dark .workflow-hero-bg {
  opacity: 0.35;
}

/* ── Edges ── */
.edge {
  fill: none;
  stroke-width: 1.5;
  stroke-linecap: round;
}

.edge-main {
  stroke: hsl(var(--primary));
  stroke-opacity: 0.22;
}

.edge-branch {
  stroke: hsl(var(--node-condition));
  stroke-opacity: 0.2;
  stroke-dasharray: 5 4;
}

.edge-secondary {
  stroke: hsl(var(--node-cron));
  stroke-opacity: 0.18;
}

/* ── Arrowheads ── */
.arrow-main {
  fill: hsl(var(--primary));
  opacity: 0.3;
}

.arrow-branch {
  fill: hsl(var(--node-condition));
  opacity: 0.25;
}

.arrow-secondary {
  fill: hsl(var(--node-cron));
  opacity: 0.25;
}

/* ── Node shared base ── */
.node-fill {
  fill-opacity: 0.07;
}

.node-ring {
  fill: none;
  stroke-width: 1.5;
  stroke-opacity: 0.3;
}

.node-accent {
  fill-opacity: 0.45;
}

.node-label {
  font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
  font-size: 9.5px;
  font-weight: 600;
  fill-opacity: 0.55;
}

.node-type-label {
  font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
  font-size: 8.5px;
  font-weight: 600;
  fill-opacity: 0.4;
}

.handle-left,
.handle-right {
  fill-opacity: 0.5;
}

/* ── Node type colors ── */
.node-trigger .node-fill   { fill: hsl(var(--node-input)); }
.node-trigger .node-ring   { stroke: hsl(var(--node-input)); }
.node-trigger .node-icon   { fill: hsl(var(--node-input)); fill-opacity: 0.65; }
.node-trigger .handle-right { fill: hsl(var(--node-input)); }
.node-trigger .node-type-label { fill: hsl(var(--node-input)); }

.node-http .node-fill   { fill: hsl(var(--node-http)); }
.node-http .node-ring   { stroke: hsl(var(--node-http)); }
.node-http .node-accent { fill: hsl(var(--node-http)); }
.node-http .node-label  { fill: hsl(var(--node-http)); }
.node-http .handle-left,
.node-http .handle-right { fill: hsl(var(--node-http)); }

.node-llm .node-fill   { fill: hsl(var(--node-llm)); }
.node-llm .node-ring   { stroke: hsl(var(--node-llm)); }
.node-llm .node-accent { fill: hsl(var(--node-llm)); }
.node-llm .node-label  { fill: hsl(var(--node-llm)); }
.node-llm .handle-left,
.node-llm .handle-right { fill: hsl(var(--node-llm)); }

.node-condition .node-fill   { fill: hsl(var(--node-condition)); }
.node-condition .node-ring   { stroke: hsl(var(--node-condition)); }
.node-condition .node-accent { fill: hsl(var(--node-condition)); }
.node-condition .node-label  { fill: hsl(var(--node-condition)); }
.node-condition .handle-left,
.node-condition .handle-right { fill: hsl(var(--node-condition)); }

.node-agent .node-fill   { fill: hsl(var(--node-agent)); }
.node-agent .node-ring   { stroke: hsl(var(--node-agent)); }
.node-agent .node-accent { fill: hsl(var(--node-agent)); }
.node-agent .node-label  { fill: hsl(var(--node-agent)); }
.node-agent .handle-left,
.node-agent .handle-right { fill: hsl(var(--node-agent)); }

.node-set .node-fill   { fill: hsl(var(--node-set)); }
.node-set .node-ring   { stroke: hsl(var(--node-set)); }
.node-set .node-accent { fill: hsl(var(--node-set)); }
.node-set .node-label  { fill: hsl(var(--node-set)); }
.node-set .handle-left,
.node-set .handle-right { fill: hsl(var(--node-set)); }

.node-merge .node-fill   { fill: hsl(var(--node-merge)); }
.node-merge .node-ring   { stroke: hsl(var(--node-merge)); }
.node-merge .node-accent { fill: hsl(var(--node-merge)); }
.node-merge .node-label  { fill: hsl(var(--node-merge)); }
.node-merge .handle-left,
.node-merge .handle-right { fill: hsl(var(--node-merge)); }

.node-output .node-fill   { fill: hsl(var(--node-output)); }
.node-output .node-ring   { stroke: hsl(var(--node-output)); }
.node-output .node-accent { fill: hsl(var(--node-output)); }
.node-output .node-label  { fill: hsl(var(--node-output)); }
.node-output .handle-left { fill: hsl(var(--node-output)); }

.node-cron .node-fill { fill: hsl(var(--node-cron)); }
.node-cron .node-ring { stroke: hsl(var(--node-cron)); }
.clock-ring  { stroke: hsl(var(--node-cron)); stroke-opacity: 0.55; stroke-width: 1.5; fill: none; }
.clock-hand  { stroke: hsl(var(--node-cron)); stroke-opacity: 0.55; stroke-width: 1.5; stroke-linecap: round; }
.node-cron .handle-right { fill: hsl(var(--node-cron)); }
.node-cron .node-type-label { fill: hsl(var(--node-cron)); }

.node-email .node-fill   { fill: hsl(var(--node-email)); }
.node-email .node-ring   { stroke: hsl(var(--node-email)); }
.node-email .node-accent { fill: hsl(var(--node-email)); }
.node-email .node-label  { fill: hsl(var(--node-email)); }
.node-email .handle-left,
.node-email .handle-right { fill: hsl(var(--node-email)); }

/* ── Animated dots ── */
.dot {
  filter: drop-shadow(0 0 3px currentColor);
}

.dot-primary   { fill: hsl(var(--primary)); opacity: 0.7; }
.dot-agent     { fill: hsl(var(--node-agent)); opacity: 0.7; }
.dot-output    { fill: hsl(var(--node-merge)); opacity: 0.75; }
.dot-secondary { fill: hsl(var(--node-cron)); opacity: 0.65; }

/* ── Reduced motion: hide dots ── */
@media (prefers-reduced-motion: reduce) {
  .dot { display: none; }
}
</style>
