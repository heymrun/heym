import { createApp, h } from "vue";
import { createPinia } from "pinia";
import { createRouter, createWebHistory } from "vue-router";

import LoginView from "@/views/LoginView.vue";

import "./styles/globals.css";

const router = createRouter({
  history: createWebHistory(),
  routes: [{ path: "/:rest(.*)", component: { render: () => null } }],
});

createApp({ render: () => h(LoginView) }).use(createPinia()).use(router).mount("#app");
