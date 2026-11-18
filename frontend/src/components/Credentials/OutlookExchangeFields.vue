<script setup lang="ts">
import { computed, ref } from "vue";
import { Eye, EyeOff } from "lucide-vue-next";

import type { CredentialType } from "@/types/credential";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { credentialsPortKey, usePort } from "@/ports";

/** Exchange Server (EWS) sign-in for an Outlook Mail or Outlook Calendar credential. */
const props = defineProps<{
  credentialType: CredentialType;
  /** Set when editing: a blank password keeps the stored one for the same login. */
  credentialId?: string;
  hasStoredPassword: boolean;
  disabled?: boolean;
}>();

const email = defineModel<string>("email", { required: true });
const username = defineModel<string>("username", { required: true });
const password = defineModel<string>("password", { required: true });
const server = defineModel<string>("server", { required: true });

const credentialsApi = usePort(credentialsPortKey);
const showPassword = ref(false);
const testing = ref(false);
const testResult = ref<{ success: boolean; message: string } | null>(null);

const canTest = computed(
  (): boolean =>
    !!email.value.trim() && (!!password.value || props.hasStoredPassword),
);

async function testConnection(): Promise<void> {
  testing.value = true;
  testResult.value = null;
  try {
    testResult.value = await credentialsApi.testConnection({
      type: props.credentialType,
      config: {
        auth_mode: "ews",
        ews_email: email.value.trim(),
        ews_username: username.value.trim(),
        ews_password: password.value,
        ews_server: server.value.trim(),
      },
      credential_id: props.credentialId,
    });
  } catch (err: unknown) {
    testResult.value = {
      success: false,
      message: err instanceof Error ? err.message : "Connection test failed",
    };
  } finally {
    testing.value = false;
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="space-y-2">
      <Label for="cred-ews-email">Email Address</Label>
      <Input
        id="cred-ews-email"
        v-model="email"
        placeholder="jane@contoso.com"
        autocomplete="off"
        :disabled="disabled"
      />
      <p class="text-xs text-muted-foreground">
        The mailbox Heym reads, sends from or books in.
      </p>
    </div>

    <div class="space-y-2">
      <Label for="cred-ews-username">User Name (optional)</Label>
      <Input
        id="cred-ews-username"
        v-model="username"
        placeholder="Same as the email address"
        autocomplete="off"
        :disabled="disabled"
      />
      <p class="text-xs text-muted-foreground">
        Leave blank to sign in with the email address, as on Outlook on the web. Enter
        <code>DOMAIN\user</code> (for example <code>CONTOSO\jane</code>) only if your
        organization signs in that way.
      </p>
    </div>

    <div class="space-y-2">
      <Label for="cred-ews-password">Password</Label>
      <div class="relative">
        <Input
          id="cred-ews-password"
          v-model="password"
          :type="showPassword ? 'text' : 'password'"
          :placeholder="hasStoredPassword ? '••••••• (leave blank to keep)' : 'Your Windows password'"
          autocomplete="new-password"
          :disabled="disabled"
          class="pr-10"
        />
        <button
          type="button"
          class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          @click="showPassword = !showPassword"
        >
          <EyeOff
            v-if="showPassword"
            class="w-4 h-4"
          />
          <Eye
            v-else
            class="w-4 h-4"
          />
        </button>
      </div>
      <p class="text-xs text-muted-foreground">
        The same password you use for Outlook. Changing the user name or server asks for it again.
      </p>
    </div>

    <div class="space-y-2">
      <Label for="cred-ews-server">Server (optional)</Label>
      <Input
        id="cred-ews-server"
        v-model="server"
        placeholder="mail.contoso.com"
        autocomplete="off"
        :disabled="disabled"
      />
      <p class="text-xs text-muted-foreground">
        Your Outlook on the web address without <code>/owa</code>. Leave it blank and Heym finds
        it from your domain's Autodiscover record.
      </p>
    </div>

    <p class="text-xs text-muted-foreground">
      For organizations that run their own Exchange Server (2013 or newer). Heym connects
      through Exchange Web Services; Microsoft 365 and Outlook.com accounts use the Microsoft
      account option.
    </p>

    <div class="flex items-center gap-3">
      <Button
        type="button"
        variant="outline"
        size="sm"
        :loading="testing"
        :disabled="disabled || testing || !canTest"
        @click="testConnection"
      >
        Test Connection
      </Button>
      <p
        v-if="testResult"
        class="text-xs"
        :class="testResult.success ? 'text-green-600 dark:text-green-400' : 'text-destructive'"
      >
        {{ testResult.message }}
      </p>
    </div>
  </div>
</template>
