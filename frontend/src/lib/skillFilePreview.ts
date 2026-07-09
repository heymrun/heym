import type { AgentSkillFile } from "@/types/workflow";

export function isSvgSkillFile(file: AgentSkillFile): boolean {
  return file.path.toLowerCase().endsWith(".svg");
}

export function isImageSkillFile(file: AgentSkillFile): boolean {
  if (isSvgSkillFile(file)) {
    return false;
  }
  return file.encoding === "base64" && (file.mimeType?.startsWith("image/") ?? false);
}

export function isTextSkillFile(file: AgentSkillFile): boolean {
  if (isSvgSkillFile(file)) {
    return true;
  }
  return !file.encoding || file.encoding === "text";
}

export function getSkillFileTextContent(file: AgentSkillFile): string {
  if (isImageSkillFile(file)) {
    return "";
  }

  if ((file.encoding ?? "text") === "base64") {
    try {
      return atob(file.content);
    } catch {
      return "(unable to decode file content)";
    }
  }

  return file.content;
}

export function getSkillFileImageSrc(file: AgentSkillFile): string {
  if (!file.content) {
    return "";
  }

  if (isSvgSkillFile(file)) {
    const svgText = getSkillFileTextContent(file);
    if (!svgText) {
      return "";
    }
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgText)}`;
  }

  if (isImageSkillFile(file)) {
    const mimeType = file.mimeType || "image/png";
    return `data:${mimeType};base64,${file.content}`;
  }

  return "";
}

export function canPreviewSkillFile(file: AgentSkillFile): boolean {
  return isTextSkillFile(file) || isImageSkillFile(file) || isSvgSkillFile(file);
}

export function isEditableSkillFile(file: AgentSkillFile): boolean {
  return isTextSkillFile(file);
}

export interface SkillFileWithIndex {
  file: AgentSkillFile;
  originalIndex: number;
}

export function compareSkillFilesForDisplay(
  left: AgentSkillFile,
  right: AgentSkillFile,
): number {
  const leftEditable = isEditableSkillFile(left);
  const rightEditable = isEditableSkillFile(right);
  if (leftEditable !== rightEditable) {
    return leftEditable ? -1 : 1;
  }

  return left.path.localeCompare(right.path);
}

export function sortSkillFiles(files: AgentSkillFile[]): AgentSkillFile[] {
  return [...files].sort(compareSkillFilesForDisplay);
}

export function getSkillFilesSortedForDisplay(
  files: AgentSkillFile[],
): SkillFileWithIndex[] {
  return files
    .map((file, originalIndex) => ({ file, originalIndex }))
    .sort((left, right) => {
      const order = compareSkillFilesForDisplay(left.file, right.file);
      if (order !== 0) {
        return order;
      }
      return left.originalIndex - right.originalIndex;
    });
}
