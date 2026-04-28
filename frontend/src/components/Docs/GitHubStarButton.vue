<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Github, Star } from "lucide-vue-next";

interface GitHubRepositoryResponse {
  stargazers_count?: unknown;
}

interface CachedStars {
  fetchedAt: number;
  stars: number;
}

const GITHUB_REPOSITORY = "heymrun/heym";
const GITHUB_REPOSITORY_URL = `https://github.com/${GITHUB_REPOSITORY}`;
const GITHUB_API_URL = `https://api.github.com/repos/${GITHUB_REPOSITORY}`;
const STAR_CACHE_KEY = "heym.github-stars";
const STAR_CACHE_TTL_MS = 10 * 60 * 1000;
const STAR_COUNT_FORMATTER = new Intl.NumberFormat("en", {
  maximumFractionDigits: 1,
  notation: "compact",
});

const stars = ref<number | null>(null);
let activeAbortController: AbortController | null = null;

const formattedStars = computed(() => {
  return stars.value === null ? null : STAR_COUNT_FORMATTER.format(stars.value);
});

const ariaLabel = computed(() => {
  return formattedStars.value
    ? `Star Heym on GitHub, ${formattedStars.value} stars`
    : "Star Heym on GitHub";
});

function readCachedStars(): number | null {
  try {
    const raw = window.sessionStorage.getItem(STAR_CACHE_KEY);
    if (!raw) return null;

    const cached = JSON.parse(raw) as Partial<CachedStars>;
    if (typeof cached.stars !== "number" || typeof cached.fetchedAt !== "number") {
      return null;
    }

    if (Date.now() - cached.fetchedAt > STAR_CACHE_TTL_MS) {
      return null;
    }

    return cached.stars;
  } catch {
    return null;
  }
}

function writeCachedStars(nextStars: number): void {
  try {
    window.sessionStorage.setItem(
      STAR_CACHE_KEY,
      JSON.stringify({ fetchedAt: Date.now(), stars: nextStars } satisfies CachedStars),
    );
  } catch {
    return;
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

async function loadStars(): Promise<void> {
  const cachedStars = readCachedStars();
  if (cachedStars !== null) {
    stars.value = cachedStars;
  }

  activeAbortController = new AbortController();

  try {
    const response = await fetch(GITHUB_API_URL, {
      headers: { Accept: "application/vnd.github+json" },
      signal: activeAbortController.signal,
    });

    if (!response.ok) return;

    const data = (await response.json()) as GitHubRepositoryResponse;
    if (typeof data.stargazers_count !== "number") return;

    stars.value = data.stargazers_count;
    writeCachedStars(data.stargazers_count);
  } catch (error: unknown) {
    if (!isAbortError(error)) {
      stars.value = cachedStars;
    }
  } finally {
    activeAbortController = null;
  }
}

onMounted(() => {
  void loadStars();
});

onUnmounted(() => {
  activeAbortController?.abort();
});
</script>

<template>
  <a
    :href="GITHUB_REPOSITORY_URL"
    target="_blank"
    rel="noopener noreferrer"
    :aria-label="ariaLabel"
    title="Star Heym on GitHub"
    class="inline-flex h-11 min-h-[44px] min-w-[44px] items-center justify-center gap-1.5 rounded-xl px-2.5 text-sm font-medium text-foreground transition-all duration-250 hover:bg-accent hover:text-accent-foreground active:scale-[0.97] md:h-9 md:min-h-[36px]"
  >
    <Github class="h-4 w-4 shrink-0" />
    <Star class="h-3.5 w-3.5 shrink-0 fill-amber-400 text-amber-500" />
    <span class="hidden text-xs font-medium sm:inline">Star</span>
    <span
      v-if="formattedStars"
      class="rounded-full bg-muted px-1.5 py-0.5 text-[11px] font-semibold leading-none text-muted-foreground"
    >
      {{ formattedStars }}
    </span>
  </a>
</template>
