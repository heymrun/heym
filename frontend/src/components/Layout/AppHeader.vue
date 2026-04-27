<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { BookOpen, LogOut, Moon, Search, Sun, User } from "lucide-vue-next";

import UserSettingsDialog from "@/components/Layout/UserSettingsDialog.vue";
import Button from "@/components/ui/Button.vue";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import { useAuthStore } from "@/stores/auth";
import { useThemeStore } from "@/stores/theme";

defineProps<{
  onOpenCommandPalette?: () => void;
  hideDocsLink?: boolean;
}>();

const router = useRouter();
const authStore = useAuthStore();
const themeStore = useThemeStore();
const showSettingsDialog = ref(false);

const appVersion = computed(() => {
  const version = import.meta.env.VITE_APP_VERSION;
  return `v${version}`;
});

onMounted(() => {
  const unsub = onDismissOverlays(() => {
    showSettingsDialog.value = false;
  });
  onUnmounted(() => unsub());
});

async function handleLogout(): Promise<void> {
  await authStore.logout();
  router.push("/login");
}
</script>

<template>
  <header class="app-header h-16 border-b border-border/40 sticky top-0 z-40 overflow-x-hidden">
    <div class="h-full px-4 md:px-6 flex items-center justify-between max-w-full overflow-x-hidden">
      <div class="flex items-center gap-1.5 sm:gap-2">
        <slot name="left-actions" />
        <router-link
          to="/"
          class="logo-link flex items-center gap-3 font-semibold cursor-pointer group"
        >
          <div class="logo-icon flex items-center justify-center w-10 h-10">
            <img
              src="/fav.svg"
              alt="Heym"
              class="w-10 h-10"
            >
          </div>
          <div class="flex flex-col">
            <span class="text-lg font-bold tracking-tight hidden sm:block group-hover:text-primary transition-colors duration-200">
              Heym
            </span>
            <span class="text-xs text-muted-foreground hidden md:block">{{ appVersion }}</span>
          </div>
        </router-link>
      </div>

      <div class="flex items-center gap-1.5 sm:gap-2">
        <router-link
          v-if="!hideDocsLink"
          to="/docs"
          class="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium text-foreground hover:bg-muted/50 transition-colors min-h-[44px] md:min-h-0"
        >
          <BookOpen class="w-4 h-4 shrink-0" />
          <span class="hidden sm:inline">Documentation</span>
        </router-link>
        <button
          v-if="authStore.user"
          type="button"
          class="user-badge hidden md:flex items-center gap-2.5 text-sm mr-2 px-3 py-2 rounded-xl cursor-pointer hover:opacity-80 transition-opacity text-left"
          title="User Settings"
          @click="showSettingsDialog = true; pushOverlayState()"
        >
          <div class="flex items-center justify-center w-7 h-7 rounded-lg bg-primary/15 text-primary shrink-0">
            <User class="w-4 h-4" />
          </div>
          <span class="font-medium text-foreground">{{ authStore.user.name }}</span>
        </button>

        <slot name="actions" />

        <Button
          v-if="onOpenCommandPalette"
          variant="ghost"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-9 md:w-9 text-foreground"
          title="Search (Ctrl+K)"
          @click="onOpenCommandPalette()"
        >
          <Search class="w-4 h-4" />
        </Button>

        <Button
          variant="ghost"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-9 md:w-9 text-foreground"
          @click="themeStore.toggle"
        >
          <Sun
            v-if="themeStore.isDark"
            class="w-4 h-4"
          />
          <Moon
            v-else
            class="w-4 h-4"
          />
        </Button>

        <Button
          variant="ghost"
          size="sm"
          class="hidden sm:inline-flex min-h-[44px] text-foreground"
          @click="handleLogout"
        >
          <LogOut class="w-4 h-4" />
          <span class="hidden md:inline">Logout</span>
        </Button>

        <Button
          variant="ghost"
          size="icon"
          class="sm:hidden h-11 w-11 min-h-[44px] min-w-[44px] text-foreground"
          @click="handleLogout"
        >
          <LogOut class="w-4 h-4" />
        </Button>
      </div>
    </div>

    <UserSettingsDialog
      :open="showSettingsDialog"
      @close="showSettingsDialog = false"
    />
  </header>
</template>

<style scoped>
.app-header {
  background: hsl(var(--background) / 0.85);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

.logo-icon {
  box-shadow: 0 4px 12px hsl(var(--primary) / 0.2);
  transition: all 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}

.logo-link:hover .logo-icon {
  box-shadow: 0 6px 20px hsl(var(--primary) / 0.3);
  transform: translateY(-1px);
}

</style>
