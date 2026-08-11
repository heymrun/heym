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

// Dashboard tabs are query-driven (`/?tab=<name>`). Expose friendly path aliases
// (e.g. `/mcp`, `/drive`) that redirect to the matching dashboard tab so links and
// manual URLs land on the right place.
const DASHBOARD_TAB_PATHS = [
  "schedules",
  "credentials",
  "globalvariables",
  "vectorstores",
  "mcp",
  "traces",
  "alerts",
  "analytics",
  "dashboard",
  "templates",
  "teams",
  "logs",
  "drive",
  "board",
  "datatable",
] as const;

const dashboardTabRoutes = DASHBOARD_TAB_PATHS.map((tab) => ({
  path: `/${tab}`,
  redirect: { path: "/", query: { tab } },
}));

const router = createRouter({
  history: createWebHistory(sanitizeRouterBase(import.meta.env.BASE_URL)),
  routes: [
    {
      path: "/workflows",
      redirect: { path: "/" },
    },
    {
      path: "/chat",
      redirect: { name: "chats" },
    },
    ...dashboardTabRoutes,
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
      path: "/workflows/:id/:executionId?",
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
      path: "/codex/followup/:token",
      name: "codex-followup",
      component: () => import("@/views/CodexFollowupView.vue"),
      meta: { guest: false, requiresAuth: false },
    },
    {
      path: "/evals",
      name: "evals",
      component: () => import("@/views/EvalsView.vue"),
      meta: { requiresAuth: true },
    },
    {
      path: "/chats",
      name: "chats",
      component: () => import("@/views/ChatsView.vue"),
      meta: { requiresAuth: true },
    },
    {
      path: "/chats/:id",
      name: "chat-detail",
      component: () => import("@/views/ChatsView.vue"),
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
