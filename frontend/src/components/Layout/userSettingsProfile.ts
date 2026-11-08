import type { User } from "@/types/auth";

export interface ProfileFormValues {
  name: string;
  userRules: string;
}

/**
 * The profile form after a fresh read of the user. Chat and MCP clients can change User Rules
 * while the dialog's cached copy is old; a field the user has not touched takes the fresh value,
 * and a field they already edited keeps their edit.
 */
export function mergeFreshProfile(
  form: ProfileFormValues,
  cached: User,
  fresh: User,
): ProfileFormValues {
  return {
    name: form.name === cached.name ? fresh.name : form.name,
    userRules:
      form.userRules === (cached.user_rules ?? "") ? (fresh.user_rules ?? "") : form.userRules,
  };
}
