const STORAGE_KEY = "heym_recent_workflows";
const MAX_RECENT = 2;

export interface RecentWorkflow {
  id: string;
  name: string;
}

export function useRecentWorkflows() {
  function getRecent(): RecentWorkflow[] {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw) as RecentWorkflow[];
      if (!Array.isArray(parsed)) return [];
      return parsed.slice(0, MAX_RECENT);
    } catch {
      return [];
    }
  }

  function addRecent(workflowId: string, name: string): void {
    const current = getRecent();
    const filtered = current.filter((w) => w.id !== workflowId);
    const updated: RecentWorkflow[] = [{ id: workflowId, name }, ...filtered].slice(0, MAX_RECENT);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
    } catch {
      // Ignore storage errors
    }
  }

  return { getRecent, addRecent };
}
