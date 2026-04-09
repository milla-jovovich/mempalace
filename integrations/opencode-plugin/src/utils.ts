import fs from 'fs';
import path from 'path';

export function getWingFromPath(workspacePath: string): string {
  if (!workspacePath || workspacePath === '/') {
    return 'wing_general';
  }

  const baseName = path.basename(workspacePath);
  const sanitized = baseName.toLowerCase().replace(/[^a-z0-9]/g, '-');
  return `wing_${sanitized}`;
}

export function isEmptyWorkspace(dir: string): boolean {
  try {
    const files = fs.readdirSync(dir);
    const ignored = new Set([
      '.git',
      '.mempalace',
      '.opencode',
      '.DS_Store',
      'node_modules',
      '.cursor',
      '.vscode',
      '.idea',
    ]);
    const meaningfulFiles = files.filter((f) => !ignored.has(f));
    return meaningfulFiles.length === 0;
  } catch (error) {
    return true;
  }
}
