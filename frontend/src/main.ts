import { createApp } from "vue";
import { createPinia } from "pinia";
import VueApexCharts from "vue3-apexcharts";
import { polyfill } from "mobile-drag-drop";
import { scrollBehaviourDragImageTranslateOverride } from "mobile-drag-drop/scroll-behaviour";

import App from "./App.vue";
import router from "./router";
import "./styles/globals.css";
import "mobile-drag-drop/default.css";

// Enable HTML5 drag-drop on mobile/touch devices (required for workflow folder/trash drop zones)
polyfill({
  forceApply: true,
  dragImageTranslateOverride: scrollBehaviourDragImageTranslateOverride,
  holdToDrag: 400,
});

// iOS Safari 10.x: required for polyfill (passive: false allows preventDefault on touch)
if (typeof window !== "undefined" && "ontouchstart" in window) {
  window.addEventListener("touchmove", () => {}, { passive: false });
}

const app = createApp(App);
const pinia = createPinia();

app.use(pinia);
app.use(router);
app.use(VueApexCharts);

import { useThemeStore } from "./stores/theme";
useThemeStore();

app.mount("#app");


