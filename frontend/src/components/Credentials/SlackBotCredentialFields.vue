<script setup lang="ts">
import { computed, ref } from "vue";
import { Check, Copy } from "lucide-vue-next";

import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { slackAppManifest, slackInteractivityUrl } from "@/components/Credentials/slackBotSetup";

const props = defineProps<{
  credentialId: string;
  publicBaseUrl: string;
  disabled?: boolean;
}>();

const botToken = defineModel<string>("botToken", { required: true });
const signingSecret = defineModel<string>("signingSecret", { required: true });
const copied = ref<"url" | "manifest" | null>(null);

const interactivityUrl = computed((): string =>
  slackInteractivityUrl(props.publicBaseUrl, props.credentialId),
);

async function copy(kind: "url" | "manifest"): Promise<void> {
  const text = kind === "url" ? interactivityUrl.value : slackAppManifest(interactivityUrl.value);
  try {
    await navigator.clipboard.writeText(text);
    copied.value = kind;
    window.setTimeout(() => {
      copied.value = null;
    }, 1500);
  } catch {
    copied.value = null;
  }
}
</script>

<template>
  <div class="space-y-2">
    <Label for="cred-slack-bot-token">Bot User OAuth Token</Label>
    <Input
      id="cred-slack-bot-token"
      v-model="botToken"
      type="password"
      autocomplete="off"
      :placeholder="credentialId ? '(re-enter to update)' : 'xoxb-...'"
      :disabled="disabled"
    />
    <p class="text-xs text-muted-foreground">
      Slack App → OAuth &amp; Permissions → Bot User OAuth Token.
    </p>
  </div>
  <div class="space-y-2">
    <Label for="cred-slack-bot-signing-secret">Signing Secret</Label>
    <Input
      id="cred-slack-bot-signing-secret"
      v-model="signingSecret"
      type="password"
      autocomplete="off"
      :placeholder="credentialId ? '(re-enter to update)' : 'Needed for approvals, buttons and forms'"
      :disabled="disabled"
    />
    <p class="text-xs text-muted-foreground">
      Slack App → Basic Information → App Credentials. Lets Heym trust clicks and Slack Trigger events.
    </p>
  </div>
  <div class="space-y-2 rounded-md border border-border bg-muted/40 p-3 text-xs">
    <p class="font-medium text-foreground">
      Interactivity Request URL
    </p>
    <div
      v-if="interactivityUrl"
      class="flex items-center gap-2"
    >
      <code class="min-w-0 flex-1 truncate rounded bg-background px-2 py-1">{{ interactivityUrl }}</code>
      <button
        type="button"
        class="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
        aria-label="Copy interactivity URL"
        @click="copy('url')"
      >
        <Check
          v-if="copied === 'url'"
          class="h-3.5 w-3.5"
        />
        <Copy
          v-else
          class="h-3.5 w-3.5"
        />
      </button>
    </div>
    <p
      v-else
      class="text-muted-foreground"
    >
      Save this credential to get its URL. Slack sends approvals, button clicks and forms there.
    </p>
    <p class="text-muted-foreground">
      Create the Slack app from a manifest to get every scope at once:
      <button
        type="button"
        class="font-medium text-primary hover:underline"
        @click="copy('manifest')"
      >
        {{ copied === 'manifest' ? 'Manifest copied' : 'Copy app manifest' }}
      </button>
    </p>
  </div>
</template>
