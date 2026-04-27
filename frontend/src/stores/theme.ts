import { ref, watch } from "vue";
import { defineStore } from "pinia";

export const useThemeStore = defineStore("theme", () => {
  const isDark = ref(localStorage.getItem("theme") !== "light");

  function toggle(): void {
    isDark.value = !isDark.value;
  }

  function setTheme(dark: boolean): void {
    isDark.value = dark;
  }

  watch(
    isDark,
    (dark) => {
      localStorage.setItem("theme", dark ? "dark" : "light");
      if (dark) {
        document.documentElement.classList.add("dark");
      } else {
        document.documentElement.classList.remove("dark");
      }
    },
    { immediate: true }
  );

  return {
    isDark,
    toggle,
    setTheme,
  };
});





