<script setup lang="ts">
import { ref } from "vue";
import { LogOut } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import { apiErrorDetail, revokeOtherSessions } from "@/services/mfa";

const busy = ref(false);
const message = ref("");
const error = ref("");

async function signOutOthers(): Promise<void> {
  busy.value = true;
  message.value = "";
  error.value = "";
  try {
    await revokeOtherSessions();
    message.value = "Every other session was signed out. This one stays signed in.";
  } catch (err) {
    error.value = apiErrorDetail(err, "Could not sign out the other sessions.");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="space-y-3 border-t border-border pt-6">
    <div class="space-y-1">
      <h3 class="text-sm font-semibold">
        Sessions
      </h3>
      <p class="text-xs text-muted-foreground">
        Sign out of every other browser and device, Heym Work, and connected MCP clients.
        Use it after signing in on a shared computer or losing a device.
      </p>
    </div>
    <Button
      type="button"
      variant="outline"
      size="sm"
      :loading="busy"
      data-testid="sign-out-other-sessions"
      @click="signOutOthers"
    >
      <LogOut class="w-4 h-4 mr-1" />
      Sign out other sessions
    </Button>
    <p
      v-if="message"
      class="text-xs text-emerald-500"
    >
      {{ message }}
    </p>
    <p
      v-if="error"
      class="text-xs text-destructive"
    >
      {{ error }}
    </p>
  </section>
</template>
