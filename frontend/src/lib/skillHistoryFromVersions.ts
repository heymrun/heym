import type { AgentSkill, WorkflowNode, WorkflowVersion } from "@/types/workflow";

export interface SkillHistoryEntry {
  versionId: string;
  versionNumber: number;
  createdAt: string;
  skill: AgentSkill;
  changeLabel: string;
}

interface SkillSnapshotComparable {
  name: string;
  content: string;
  files: AgentSkill["files"];
  timeoutSeconds: number | undefined;
  driveFilesEnabled: boolean | undefined;
}

function cloneSkill(skill: AgentSkill): AgentSkill {
  return {
    ...skill,
    files: skill.files?.map((file) => ({ ...file })),
  };
}

export function findAgentNode(
  nodes: WorkflowNode[],
  agentNodeId: string,
): WorkflowNode | undefined {
  return nodes.find((node) => node.id === agentNodeId && node.type === "agent");
}

export function findSkillInNode(
  node: WorkflowNode,
  skillId: string,
): AgentSkill | undefined {
  const skills = node.data.skills ?? [];
  return skills.find((skill) => skill.id === skillId);
}

export function normalizeSkillForCompare(skill: AgentSkill): SkillSnapshotComparable {
  return {
    name: skill.name,
    content: skill.content,
    files: skill.files?.map((file) => ({
      path: file.path,
      content: file.content,
      encoding: file.encoding,
      mimeType: file.mimeType,
    })),
    timeoutSeconds: skill.timeoutSeconds,
    driveFilesEnabled: skill.driveFilesEnabled,
  };
}

export function areSkillSnapshotsEqual(a: AgentSkill, b: AgentSkill): boolean {
  return (
    JSON.stringify(normalizeSkillForCompare(a)) === JSON.stringify(normalizeSkillForCompare(b))
  );
}

export function getSkillTimeoutSeconds(skill: AgentSkill): number {
  return skill.timeoutSeconds ?? 30;
}

function haveSkillFilesChanged(previous: AgentSkill, current: AgentSkill): boolean {
  const previousFiles = previous.files ?? [];
  const currentFiles = current.files ?? [];
  if (previousFiles.length !== currentFiles.length) {
    return true;
  }
  return JSON.stringify(
    previousFiles.map((file) => ({
      path: file.path,
      content: file.content,
      encoding: file.encoding,
      mimeType: file.mimeType,
    })),
  ) !== JSON.stringify(
    currentFiles.map((file) => ({
      path: file.path,
      content: file.content,
      encoding: file.encoding,
      mimeType: file.mimeType,
    })),
  );
}

export function getSkillChangeLabels(previous: AgentSkill | null, current: AgentSkill): string[] {
  if (!previous) {
    return ["Added"];
  }

  const changes: string[] = [];
  if (previous.name !== current.name) {
    changes.push("Name");
  }
  if (previous.content !== current.content) {
    changes.push("Content");
  }
  if (haveSkillFilesChanged(previous, current)) {
    changes.push("Files");
  }
  if (getSkillTimeoutSeconds(previous) !== getSkillTimeoutSeconds(current)) {
    changes.push("Timeout");
  }
  if (!!previous.driveFilesEnabled !== !!current.driveFilesEnabled) {
    changes.push("Drive access");
  }

  return changes;
}

function getChangeLabel(previous: AgentSkill | null, current: AgentSkill): string {
  const changes = getSkillChangeLabels(previous, current);
  if (changes.length === 0) {
    return "Unchanged";
  }
  if (changes.length === 1) {
    return changes[0] ?? "Modified";
  }
  return changes.join(", ");
}

function extractSkillSnapshot(
  nodes: WorkflowNode[],
  agentNodeId: string,
  skillId: string,
): AgentSkill | null {
  const node = findAgentNode(nodes, agentNodeId);
  if (!node) {
    return null;
  }
  const skill = findSkillInNode(node, skillId);
  return skill ? cloneSkill(skill) : null;
}

export function buildSkillHistoryEntries(
  versions: WorkflowVersion[],
  currentNodes: WorkflowNode[],
  agentNodeId: string,
  skillId: string,
  currentUpdatedAt: string,
): SkillHistoryEntry[] {
  const rawEntries: SkillHistoryEntry[] = [];

  const currentSkill = extractSkillSnapshot(currentNodes, agentNodeId, skillId);
  if (currentSkill) {
    const maxVersionNumber = versions.reduce(
      (max, version) => Math.max(max, version.version_number),
      0,
    );
    rawEntries.push({
      versionId: "current",
      versionNumber: maxVersionNumber + 1,
      createdAt: currentUpdatedAt,
      skill: currentSkill,
      changeLabel: "Current",
    });
  }

  const sortedVersions = [...versions].sort((a, b) => b.version_number - a.version_number);
  for (const version of sortedVersions) {
    const skill = extractSkillSnapshot(version.nodes, agentNodeId, skillId);
    if (!skill) {
      continue;
    }
    rawEntries.push({
      versionId: version.id,
      versionNumber: version.version_number,
      createdAt: version.created_at,
      skill,
      changeLabel: "Snapshot",
    });
  }

  const deduped: SkillHistoryEntry[] = [];
  let previousSkill: AgentSkill | null = null;
  for (const entry of rawEntries) {
    if (previousSkill && areSkillSnapshotsEqual(previousSkill, entry.skill)) {
      continue;
    }
    const changeLabel =
      entry.versionId === "current"
        ? "Current"
        : getChangeLabel(previousSkill, entry.skill);
    deduped.push({
      ...entry,
      changeLabel,
    });
    previousSkill = entry.skill;
  }

  return deduped;
}

export function getSkillHistorySummary(skill: AgentSkill): string {
  const fileCount = skill.files?.length ?? 0;
  const contentLength = skill.content.length;
  const timeoutSeconds = getSkillTimeoutSeconds(skill);
  const fileLabel = fileCount === 1 ? "1 file" : `${fileCount} files`;
  return `${timeoutSeconds}s timeout · ${contentLength} chars · ${fileLabel}`;
}

export function formatSkillTimeoutChange(
  older: AgentSkill | null,
  newer: AgentSkill | null,
): string | null {
  if (!older || !newer) {
    return null;
  }
  const olderTimeout = getSkillTimeoutSeconds(older);
  const newerTimeout = getSkillTimeoutSeconds(newer);
  if (olderTimeout === newerTimeout) {
    return null;
  }
  return `${olderTimeout}s → ${newerTimeout}s`;
}
