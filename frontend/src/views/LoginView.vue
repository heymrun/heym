<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import axios from "axios";
import { ArrowRight, KeyRound, Sparkles, Zap } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import WorkflowHeroBackground from "@/components/Layout/WorkflowHeroBackground.vue";
import { getSsoStatus } from "@/services/sso";
import { useAuthStore } from "@/stores/auth";
import type { SsoStatus } from "@/types/sso";

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();

const email = ref("");
const password = ref("");
const error = ref("");
const loading = ref(false);
const sso = ref<SsoStatus>({
  enabled: false,
  button_label: "Sign in with SSO",
  password_login_enabled: true,
});
// When password sign-in is disabled instance-wide the form is hidden, but accounts in
// HEYM_ADMIN_EMAILS are still allowed through. Without a way to reveal the form, that
// break-glass exemption would be unreachable and a provider outage would strand everyone.
const showAdminSignIn = ref(false);

const passwordFormVisible = computed(
  () => sso.value.password_login_enabled || showAdminSignIn.value,
);

const SSO_ERRORS: Record<string, string> = {
  state_mismatch: "That sign-in attempt expired. Please try again.",
  token_exchange_failed: "Could not reach the identity provider. Try again shortly.",
  invalid_token: "The identity provider's response could not be verified.",
  email_missing: "The identity provider did not return an email address.",
  email_not_verified: "Your email address is not verified with the identity provider.",
  domain_not_allowed: "Your email domain is not allowed on this instance.",
  provisioning_disabled: "No Heym account exists for you. Ask an administrator to create one.",
  sso_disabled: "Single sign-on is not configured on this instance.",
};

const ssoError = computed<string>(() => {
  const code = route.query.sso_error;
  return typeof code === "string" ? (SSO_ERRORS[code] ?? SSO_ERRORS.invalid_token) : "";
});

async function handleSubmit(): Promise<void> {
  error.value = "";
  loading.value = true;

  try {
    await authStore.login({ email: email.value, password: password.value });
    router.push("/");
  } catch (err) {
    const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
    error.value =
      typeof detail === "string" && err instanceof Error && axios.isAxiosError(err)
      && err.response?.status === 403
        ? detail
        : "Invalid email or password";
  } finally {
    loading.value = false;
  }
}

function startSso(): void {
  // A full navigation, not an XHR: the browser must follow the redirect chain into the
  // provider's own login UI.
  window.location.href = "/api/auth/sso/login";
}

onMounted(async () => {
  try {
    sso.value = await getSsoStatus();
  } catch {
    // A status failure must never hide the password form.
    sso.value = { enabled: false, button_label: "Sign in with SSO", password_login_enabled: true };
  }
});
</script>

<template>
  <div class="auth-container min-h-screen flex items-center justify-center bg-background p-4 overflow-x-hidden relative">
    <div class="absolute inset-0 overflow-hidden">
      <div class="auth-blob auth-blob-1" />
      <div class="auth-blob auth-blob-2" />
      <div class="auth-blob auth-blob-3" />
      <div class="auth-grid absolute inset-0 bg-grid-pattern opacity-30" />
    </div>
    <div class="absolute inset-0 bg-background/70 backdrop-blur-3xl" />

    <!-- Workflow graph background (above blur, below card) -->
    <WorkflowHeroBackground />

    <div class="relative z-10 w-full max-w-full sm:max-w-md pt-14 sm:pt-16">
      <div class="auth-badge absolute top-0 left-1/2 -translate-x-1/2 flex items-center gap-2 px-5 py-2.5 rounded-full bg-card border border-primary/25 text-primary text-sm font-medium whitespace-nowrap before:absolute before:inset-0 before:rounded-full before:bg-primary/10 before:content-['']">
        <Sparkles class="relative w-4 h-4" />
        <span class="relative">AI Workflow Automation</span>
      </div>

      <Card class="auth-card relative w-full px-6 py-10 md:px-8 md:py-12 lg:px-9 lg:py-14 animate-scale-in-bounce gradient-border-hover">
        <div class="flex flex-col items-center mb-12">
          <img
            src="/fav.svg"
            alt="Heym"
            class="w-20 h-20 mb-7"
          >
          <h1 class="text-3xl md:text-4xl font-bold tracking-tight text-center">
            Welcome back
          </h1>
          <p class="text-muted-foreground text-base mt-3 text-center max-w-[340px]">
            {{
              passwordFormVisible
                ? "Sign in to continue building powerful AI workflows"
                : "This workspace signs in through your identity provider"
            }}
          </p>
        </div>

        <div
          v-if="ssoError"
          class="mb-5 p-4 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm"
        >
          {{ ssoError }}
        </div>

        <form
          v-if="passwordFormVisible"
          class="space-y-5"
          @submit.prevent="handleSubmit"
        >
          <Transition
            enter-active-class="transition-all duration-300"
            leave-active-class="transition-all duration-200"
            enter-from-class="opacity-0 -translate-y-2"
            leave-to-class="opacity-0 -translate-y-2"
          >
            <div
              v-if="error"
              class="p-4 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm flex items-center gap-3"
            >
              <div class="w-2 h-2 rounded-full bg-destructive animate-pulse" />
              <span class="font-medium">{{ error }}</span>
            </div>
          </Transition>

          <div class="space-y-2.5">
            <Label
              for="email"
              class="text-sm font-medium"
            >
              Email address
            </Label>
            <Input
              id="email"
              v-model="email"
              type="email"
              placeholder="you@example.com"
              required
              class="h-12"
            />
          </div>

          <div class="space-y-2.5">
            <Label
              for="password"
              class="text-sm font-medium"
            >
              Password
            </Label>
            <Input
              id="password"
              v-model="password"
              type="password"
              placeholder="Enter your password"
              required
              class="h-12"
            />
          </div>

          <Button
            type="submit"
            variant="gradient"
            class="w-full h-12 min-h-[44px] text-base"
            :loading="loading"
          >
            Sign in
            <ArrowRight class="w-4 h-4 ml-1" />
          </Button>
        </form>

        <div
          v-if="sso.enabled && passwordFormVisible"
          class="divider relative my-8"
        >
          <div class="absolute inset-0 flex items-center">
            <div class="w-full border-t border-border" />
          </div>
          <div class="relative flex justify-center text-xs uppercase">
            <span class="bg-card px-3 text-muted-foreground">or</span>
          </div>
        </div>

        <div :class="passwordFormVisible ? '' : 'space-y-12 py-4'">
          <Button
            v-if="sso.enabled"
            type="button"
            variant="outline"
            class="w-full h-14 min-h-[44px] text-base"
            @click="startSso"
          >
            <KeyRound class="w-4 h-4 mr-1" />
            {{ sso.button_label }}
          </Button>

          <button
            v-if="!sso.password_login_enabled && !showAdminSignIn"
            type="button"
            class="w-full text-sm text-muted-foreground hover:text-foreground transition-colors underline underline-offset-4"
            @click="showAdminSignIn = true"
          >
            Sign in with a password instead
          </button>

          <p
            v-if="!sso.password_login_enabled && showAdminSignIn"
            class="text-xs text-muted-foreground text-center"
          >
            Password sign-in is off here. Only instance administrators can use this form.
          </p>
        </div>

        <div
          v-if="sso.password_login_enabled"
          class="divider relative my-8"
        >
          <div class="absolute inset-0 flex items-center">
            <div class="w-full border-t border-border" />
          </div>
          <div class="relative flex justify-center text-xs uppercase">
            <span class="bg-card px-3 text-muted-foreground">New to Heym?</span>
          </div>
        </div>

        <router-link
          v-if="sso.password_login_enabled"
          to="/register"
          class="register-link flex items-center justify-center gap-3 w-full h-12 min-h-[44px] rounded-xl border border-border bg-muted/30 text-sm font-medium text-foreground hover:bg-muted/50 hover:border-primary/30 transition-all duration-300"
        >
          <Zap class="w-4 h-4 text-primary" />
          Create an account
        </router-link>
      </Card>
    </div>
  </div>
</template>

<style scoped>
.auth-container {
  background: radial-gradient(
    ellipse 80% 50% at 50% -20%,
    hsl(var(--primary) / 0.08) 0%,
    transparent 60%
  );
}

.auth-grid {
  mask-image: radial-gradient(
    ellipse 60% 50% at 50% 50%,
    black 20%,
    transparent 70%
  );
}

.auth-card {
  background: hsl(var(--card) / 0.95);
  backdrop-filter: blur(20px);
}

.auth-badge {
  animation-delay: 0.2s;
}

.register-link:hover {
  transform: translateY(-1px);
}
</style>
