import JSZip from "jszip";

import type { AgentSkill, AgentSkillFile } from "@/types/workflow";

const SKILL_MD_PATTERN = /SKILL\.md$/i;
const ROOT_SKILL_FILE = "SKILL.md";
const IMAGE_MIME_BY_EXTENSION: Record<string, string> = {
  gif: "image/gif",
  jpeg: "image/jpeg",
  jpg: "image/jpeg",
  png: "image/png",
  svg: "image/svg+xml",
  webp: "image/webp",
};
const TEXT_FILE_EXTENSIONS = new Set([
  "c",
  "conf",
  "cpp",
  "css",
  "csv",
  "env",
  "gitignore",
  "html",
  "ini",
  "java",
  "js",
  "json",
  "jsx",
  "md",
  "py",
  "rb",
  "sh",
  "sql",
  "toml",
  "ts",
  "tsx",
  "txt",
  "xml",
  "yaml",
  "yml",
]);

interface ParsedSkillZipFile extends AgentSkillFile {
  encoding: "text" | "base64";
}

export function extractNameFromFrontmatter(content: string): string {
  const match = content.match(/^---\s*\n([\s\S]*?)\n---/);
  if (!match) return "";
  const frontmatter = match[1];
  const nameMatch = frontmatter.match(/^name:\s*(.+)$/m);
  return nameMatch ? nameMatch[1].trim().replace(/^["']|["']$/g, "") : "";
}

function normalizePath(p: string): string {
  return p.replace(/\\/g, "/").replace(/\/+/g, "/");
}

function normalizeArchivePath(path: string): string {
  const normalized = normalizePath(path).replace(/^\/+/, "");
  const parts = normalized
    .split("/")
    .filter((part) => part.length > 0 && part !== "." && part !== "..");
  return parts.join("/");
}

function addSkillFileToZip(zip: JSZip, file: AgentSkillFile): void {
  const path = normalizeArchivePath(file.path);
  if (!path) return;

  if ((file.encoding ?? "text") === "base64") {
    zip.file(path, file.content, { base64: true });
    return;
  }

  zip.file(path, file.content);
}

export function getSkillZipFileName(name: string, fallback = "skill"): string {
  const safeName = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return `${safeName || fallback}.zip`;
}

export async function createSkillFilesZipBlob(files: AgentSkillFile[]): Promise<Blob> {
  const zip = new JSZip();

  files.forEach((file) => {
    addSkillFileToZip(zip, file);
  });

  return zip.generateAsync({ type: "blob" });
}

export async function createAgentSkillZipBlob(skill: AgentSkill): Promise<Blob> {
  const zip = new JSZip();
  zip.file(ROOT_SKILL_FILE, skill.content);

  (skill.files ?? []).forEach((file) => {
    if (normalizeArchivePath(file.path).toLowerCase() === ROOT_SKILL_FILE.toLowerCase()) {
      return;
    }

    addSkillFileToZip(zip, file);
  });

  return zip.generateAsync({ type: "blob" });
}

function getDirectory(path: string): string {
  const norm = normalizePath(path);
  const lastSlash = norm.lastIndexOf("/");
  return lastSlash >= 0 ? norm.slice(0, lastSlash) : "";
}

function pathUnderDir(filePath: string, dir: string): boolean {
  const norm = normalizePath(filePath);
  if (!dir) return !norm.includes("/");
  return norm === dir || norm.startsWith(dir + "/");
}

function getExtension(path: string): string {
  const normalized = normalizePath(path);
  const lastDot = normalized.lastIndexOf(".");
  if (lastDot < 0) return "";
  return normalized.slice(lastDot + 1).toLowerCase();
}

function inferMimeType(path: string): string {
  const extension = getExtension(path);
  if (extension in IMAGE_MIME_BY_EXTENSION) {
    return IMAGE_MIME_BY_EXTENSION[extension];
  }
  if (extension === "md") return "text/markdown";
  if (extension === "json") return "application/json";
  if (extension === "csv") return "text/csv";
  if (TEXT_FILE_EXTENSIONS.has(extension)) return "text/plain";
  return "application/octet-stream";
}

function hasNullBytes(bytes: Uint8Array): boolean {
  return bytes.includes(0);
}

function decodeUtf8(bytes: Uint8Array): string | null {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}

function looksLikeBinaryText(decoded: string): boolean {
  let suspiciousChars = 0;
  for (const char of decoded) {
    const codePoint = char.charCodeAt(0);
    const isAllowedControl =
      codePoint === 9 || codePoint === 10 || codePoint === 13 || codePoint === 12;
    if (codePoint < 32 && !isAllowedControl) {
      suspiciousChars += 1;
    }
  }
  return suspiciousChars > 0;
}

function bytesToBase64(bytes: Uint8Array): string {
  const chunkSize = 0x8000;
  let binary = "";

  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }

  return btoa(binary);
}

function parseZipFile(path: string, bytes: Uint8Array): ParsedSkillZipFile {
  const mimeType = inferMimeType(path);
  const extension = getExtension(path);
  const decoded = decodeUtf8(bytes);
  const shouldTreatAsText =
    decoded !== null &&
    !hasNullBytes(bytes) &&
    !looksLikeBinaryText(decoded) &&
    (mimeType.startsWith("text/") ||
      mimeType === "application/json" ||
      TEXT_FILE_EXTENSIONS.has(extension));

  if (shouldTreatAsText) {
    return {
      path: normalizePath(path),
      content: decoded,
      encoding: "text",
      mimeType,
    };
  }

  return {
    path: normalizePath(path),
    content: bytesToBase64(bytes),
    encoding: "base64",
    mimeType,
  };
}

/**
 * Assign each file to the skill with the longest matching directory prefix.
 */
function assignFilesToSkills(
  fileEntries: ParsedSkillZipFile[],
  skillDirs: { dir: string; index: number }[]
): Map<number, AgentSkillFile[]> {
  const bySkill = new Map<number, AgentSkillFile[]>();

  for (const file of fileEntries) {
    if (SKILL_MD_PATTERN.test(file.path)) continue;

    let bestIndex = -1;
    let bestLen = -1;

    for (const { dir, index } of skillDirs) {
      if (pathUnderDir(file.path, dir)) {
        const len = dir.length;
        if (len > bestLen) {
          bestLen = len;
          bestIndex = index;
        }
      }
    }

    if (bestIndex >= 0) {
      const list = bySkill.get(bestIndex) ?? [];
      list.push({
        path: file.path,
        content: file.content,
        encoding: file.encoding,
        mimeType: file.mimeType,
      });
      bySkill.set(bestIndex, list);
    }
  }

  return bySkill;
}

/**
 * Parse a zip file into one or more AgentSkill entries.
 * - Each SKILL.md becomes one skill
 * - Files are assigned to the skill whose directory is the longest prefix of the file path
 * - Root SKILL.md gets root-level files
 */
export async function parseSkillZip(file: File): Promise<AgentSkill[]> {
  const arrayBuffer = await file.arrayBuffer();
  const zip = await JSZip.loadAsync(arrayBuffer);

  const fileEntries: ParsedSkillZipFile[] = [];

  const fileNames = Object.keys(zip.files).filter((n) => !zip.files[n].dir);

  for (const path of fileNames) {
    const entry = zip.files[path];
    if (!entry || entry.dir) continue;
    try {
      const bytes = await entry.async("uint8array");
      fileEntries.push(parseZipFile(path, bytes));
    } catch {
      // Skip unreadable files
    }
  }

  const skillMdEntries = fileEntries.filter(
    (e) => SKILL_MD_PATTERN.test(e.path) && e.encoding === "text"
  );
  if (skillMdEntries.length === 0) {
    throw new Error("Invalid skill zip: missing SKILL.md");
  }

  const filesBySkill =
    skillMdEntries.length === 1
      ? new Map([
          [
            0,
            fileEntries
              .filter((e) => !SKILL_MD_PATTERN.test(e.path))
              .map((e) => ({
                path: e.path,
                content: e.content,
                encoding: e.encoding,
                mimeType: e.mimeType,
              })),
          ],
        ])
      : assignFilesToSkills(
          fileEntries,
          skillMdEntries.map((e, i) => ({ dir: getDirectory(e.path), index: i }))
        );

  const skills: AgentSkill[] = skillMdEntries.map((skillMd, i) => {
    const skillDir = getDirectory(skillMd.path);
    const skillFiles = filesBySkill.get(i);

    const name =
      extractNameFromFrontmatter(skillMd.content) ||
      (skillDir ? skillDir.split("/").pop() : "skill") ||
      "skill";

    return {
      id: crypto.randomUUID(),
      name,
      content: skillMd.content,
      files: skillFiles && skillFiles.length > 0 ? skillFiles : undefined,
      timeoutSeconds: 30,
    };
  });

  return skills;
}
