<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { ArrowRight, Sparkles, Zap } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import WorkflowHeroBackground from "@/components/Layout/WorkflowHeroBackground.vue";
import { useAuthStore } from "@/stores/auth";

const router = useRouter();
const authStore = useAuthStore();

const email = ref("");
const password = ref("");
const error = ref("");
const loading = ref(false);

async function handleSubmit(): Promise<void> {
  error.value = "";
  loading.value = true;

  try {
    await authStore.login({ email: email.value, password: password.value });
    router.push("/");
  } catch {
    error.value = "Invalid email or password";
  } finally {
    loading.value = false;
  }
}
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
      <div class="auth-badge absolute top-0 left-1/2 -translate-x-1/2 flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 border border-primary/20 text-primary text-sm font-medium whitespace-nowrap">
        <Sparkles class="w-4 h-4" />
        AI Workflow Automation
      </div>

      <Card class="auth-card relative w-full p-6 md:p-8 lg:p-10 animate-scale-in-bounce gradient-border-hover">
        <div class="flex flex-col items-center mb-8">
          <img
            src="/fav.svg"
            alt="Heym"
            class="w-16 h-16 mb-6"
          >
          <h1 class="text-2xl md:text-3xl font-bold tracking-tight text-center">
            Welcome back
          </h1>
          <p class="text-muted-foreground text-sm mt-2 text-center max-w-[280px]">
            Sign in to continue building powerful AI workflows
          </p>
        </div>

        <form
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

        <div class="divider relative my-8">
          <div class="absolute inset-0 flex items-center">
            <div class="w-full border-t border-border" />
          </div>
          <div class="relative flex justify-center text-xs uppercase">
            <span class="bg-card px-3 text-muted-foreground">New to Heym?</span>
          </div>
        </div>

        <router-link
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
