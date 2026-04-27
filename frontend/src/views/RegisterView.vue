<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { ArrowRight, CheckCircle2, LogIn } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import WorkflowHeroBackground from "@/components/Layout/WorkflowHeroBackground.vue";
import { useAuthStore } from "@/stores/auth";

const router = useRouter();
const authStore = useAuthStore();

const name = ref("");
const email = ref("");
const password = ref("");
const confirmPassword = ref("");
const error = ref("");
const loading = ref(false);

async function handleSubmit(): Promise<void> {
  error.value = "";

  if (password.value !== confirmPassword.value) {
    error.value = "Passwords do not match";
    return;
  }

  if (password.value.length < 6) {
    error.value = "Password must be at least 6 characters";
    return;
  }

  loading.value = true;

  try {
    await authStore.register({
      name: name.value,
      email: email.value,
      password: password.value,
    });
    router.push("/");
  } catch (err: unknown) {
    const axiosErr = err as { response?: { status?: number; data?: { detail?: string } } };
    if (axiosErr.response?.status === 403 && axiosErr.response?.data?.detail === "Registration is disabled") {
      error.value = "Signups are currently closed. We're not accepting new accounts right now.";
    } else if (axiosErr.response?.data?.detail) {
      error.value = typeof axiosErr.response.data.detail === "string"
        ? axiosErr.response.data.detail
        : "Registration failed. Please try again.";
    } else {
      error.value = "Registration failed. Please try again.";
    }
  } finally {
    loading.value = false;
  }
}

const features = [
  "Visual workflow builder",
  "AI-powered automation",
  "Unlimited executions",
];
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

    <div class="relative z-10 w-full max-w-full sm:max-w-md">
      <Card class="auth-card relative w-full p-6 md:p-8 lg:p-10 animate-scale-in-bounce gradient-border-hover">
        <div class="flex flex-col items-center mb-8">
          <img
            src="/fav.svg"
            alt="Heym"
            class="w-16 h-16 mb-6"
          >
          <h1 class="text-2xl md:text-3xl font-bold tracking-tight text-center">
            Create your account
          </h1>
          <p class="text-muted-foreground text-sm mt-2 text-center max-w-[280px]">
            Join thousands building AI workflows
          </p>
        </div>

        <div class="features-list flex items-center justify-center flex-wrap gap-2 mb-6 text-xs text-muted-foreground">
          <div
            v-for="feature in features"
            :key="feature"
            class="flex items-center gap-1.5"
          >
            <CheckCircle2 class="w-3.5 h-3.5 text-primary" />
            <span>{{ feature }}</span>
          </div>
        </div>

        <form
          class="space-y-4"
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

          <div class="space-y-2">
            <Label
              for="name"
              class="text-sm font-medium"
            >
              Full name
            </Label>
            <Input
              id="name"
              v-model="name"
              type="text"
              placeholder="John Doe"
              required
              class="h-11 min-h-[44px]"
            />
          </div>

          <div class="space-y-2">
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
              class="h-11 min-h-[44px]"
            />
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div class="space-y-2">
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
                placeholder="Min 6 chars"
                required
                class="h-11 min-h-[44px]"
              />
            </div>

            <div class="space-y-2">
              <Label
                for="confirmPassword"
                class="text-sm font-medium"
              >
                Confirm
              </Label>
              <Input
                id="confirmPassword"
                v-model="confirmPassword"
                type="password"
                placeholder="Confirm"
                required
                class="h-11 min-h-[44px]"
              />
            </div>
          </div>

          <Button
            type="submit"
            variant="gradient"
            class="w-full h-12 min-h-[44px] text-base mt-2"
            :loading="loading"
          >
            Create account
            <ArrowRight class="w-4 h-4 ml-1" />
          </Button>
        </form>

        <div class="divider relative my-8">
          <div class="absolute inset-0 flex items-center">
            <div class="w-full border-t border-border" />
          </div>
          <div class="relative flex justify-center text-xs uppercase">
            <span class="bg-card px-3 text-muted-foreground">Already have an account?</span>
          </div>
        </div>

        <router-link
          to="/login"
          class="login-link flex items-center justify-center gap-3 w-full h-12 min-h-[44px] rounded-xl border border-border bg-muted/30 text-sm font-medium text-foreground hover:bg-muted/50 hover:border-primary/30 transition-all duration-300"
        >
          <LogIn class="w-4 h-4 text-primary" />
          Sign in instead
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

.login-link:hover {
  transform: translateY(-1px);
}

.features-list {
  flex-wrap: wrap;
  gap: 12px 16px;
}

@media (max-width: 480px) {
  .features-list {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
