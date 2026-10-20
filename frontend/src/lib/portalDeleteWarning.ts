export function portalDeleteWarning(context: { isLastUser: boolean; portalEnabled: boolean | null }): string | null {
  if (!context.isLastUser || context.portalEnabled === false) return null;
  return "Deleting the last portal user will make the portal publicly accessible again. Anyone with the portal URL will be able to run this workflow without logging in. Delete the last user and continue?";
}
