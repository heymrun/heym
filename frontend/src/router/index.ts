import { createRouter, createWebHistory } from "vue-router";

import { useAuthStore } from "@/stores/auth";

function sanitizeRouterBase(raw: unknown): string {
  if (typeof raw !== "string" || raw === "undefined" || raw === "null") {
    return "/";
  }
  const trimmed = raw.trim();
  if (trimmed === "") {
    return "/";
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

const router = createRouter({
  history: createWebHistory(sanitizeRouterBase(import.meta.env.BASE_URL)),
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("@/views/LoginView.vue"),
      meta: { guest: true },
    },
    {
      path: "/register",
      name: "register",
      component: () => import("@/views/RegisterView.vue"),
      meta: { guest: true },
    },
    {
      path: "/",
      name: "dashboard",
      component: () => import("@/views/DashboardView.vue"),
      meta: { requiresAuth: true },
    },
    {
      path: "/workflows/:id",
      name: "editor",
      component: () => import("@/views/EditorView.vue"),
      meta: { requiresAuth: true },
    },
    {
      path: "/chat/:slug",
      name: "chat-portal",
      component: () => import("@/views/ChatPortalView.vue"),
      meta: { guest: false, requiresAuth: false },
    },
    {
      path: "/review/:token",
      name: "hitl-review",
      component: () => import("@/views/HITLReviewView.vue"),
      meta: { guest: false, requiresAuth: false },
    },
    {
      path: "/evals",
      name: "evals",
      component: () => import("@/views/EvalsView.vue"),
      meta: { requiresAuth: true },
    },
    {
      path: "/picker-callback",
      name: "picker-callback",
      component: () => import("@/views/PickerCallbackView.vue"),
      meta: { guest: false, requiresAuth: false },
    },
    {
      path: "/docs",
      redirect: "/docs/getting-started/introduction",
    },
    {
      path: "/docs/:pathMatch(.*)*",
      name: "docs",
      component: () => import("@/views/DocsView.vue"),
      meta: { requiresAuth: true },
    },
  ],
});

router.beforeEach(async (to, _from, next) => {
  const authStore = useAuthStore();

  if (!authStore.initialized) {
    await authStore.fetchUser();
  }

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next({ name: "login" });
  } else if (to.meta.guest && authStore.isAuthenticated) {
    next({ name: "dashboard" });
  } else {
    next();
  }
});

export default router;
