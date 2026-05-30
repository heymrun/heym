<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { BookOpen, ExternalLink, LogOut, Moon, Search, Sun, User } from "lucide-vue-next";

import UserSettingsDialog from "@/components/Layout/UserSettingsDialog.vue";
import Button from "@/components/ui/Button.vue";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import { useAuthStore } from "@/stores/auth";
import { useThemeStore } from "@/stores/theme";
import { useVersionStore } from "@/stores/version";
import { useVoiceStore } from "@/stores/voice";

defineProps<{
  onOpenCommandPalette?: () => void;
  hideDocsLink?: boolean;
}>();

const router = useRouter();
const authStore = useAuthStore();
const themeStore = useThemeStore();
const versionStore = useVersionStore();
const voiceStore = useVoiceStore();
const showSettingsDialog = ref(false);
const settingsInitialTab = ref<"profile" | "security" | "voice">("profile");

watch(
  () => voiceStore.openVoiceSettingsSignal,
  () => {
    settingsInitialTab.value = "voice";
    showSettingsDialog.value = true;
    pushOverlayState();
  },
);

const appVersion = computed((): string => {
  return versionStore.displayVersion;
});

onMounted(() => {
  void versionStore.loadVersionInfo({ force: true });
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
        <div class="logo-link flex items-center gap-3 font-semibold group">
          <router-link
            to="/"
            class="logo-icon flex items-center justify-center w-9 h-9 cursor-pointer"
          >
            <img
              src="/fav.svg"
              alt="Heym"
              class="block w-9 h-9"
            >
          </router-link>
          <div class="flex flex-col">
            <router-link
              to="/"
              class="text-lg font-bold tracking-tight hidden sm:block group-hover:text-primary transition-colors duration-200 cursor-pointer"
            >
              Heym
            </router-link>
            <a
              v-if="versionStore.updateHref"
              :href="versionStore.updateHref"
              target="_blank"
              rel="noopener noreferrer"
              :title="versionStore.updateTitle"
              class="hidden md:flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <span>{{ appVersion }}</span>
              <span class="inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/15 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-violet-700 dark:text-violet-300">
                Update
                <ExternalLink class="h-2.5 w-2.5" />
              </span>
            </a>
            <router-link
              v-else
              to="/"
              :title="versionStore.updateTitle"
              class="text-xs text-muted-foreground hover:text-foreground hidden md:block transition-colors"
            >
              {{ appVersion }}
            </router-link>
          </div>
        </div>
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
          @click="settingsInitialTab = 'profile'; showSettingsDialog = true; pushOverlayState()"
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
      :initial-tab="settingsInitialTab"
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
  transition: all 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}

.logo-link:hover .logo-icon {
  transform: translateY(-1px);
}

</style>
