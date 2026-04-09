import execa from 'execa';
import path from 'path';

async function executeMempalace(args: string[], options: any = {}): Promise<any> {
  const defaultOptions = {
    timeout: 5000, // 5 seconds timeout to prevent hanging
    ...options,
  };

  const commands = [
    { cmd: 'mempalace', args: args },
    { cmd: 'python3', args: ['-m', 'mempalace', ...args] },
    { cmd: 'python', args: ['-m', 'mempalace', ...args] },
  ];

  let lastError;
  for (const { cmd, args: cmdArgs } of commands) {
    try {
      return await execa(cmd, cmdArgs, defaultOptions);
    } catch (error: any) {
      lastError = error;
      // If it's a timeout, don't try other commands, just fail fast
      if (error.timedOut) break;
    }
  }
  throw lastError;
}

export async function isInitialized(dir: string): Promise<boolean> {
  try {
    const palacePath = path.join(dir, '.mempalace', 'palace');
    await executeMempalace(['status', '--palace', palacePath]);
    return true;
  } catch (error) {
    return false;
  }
}

export async function initialize(dir: string): Promise<void> {
  try {
    await executeMempalace(['init', '--yes', dir], { input: '\n' });
  } catch (error) {
    console.warn(`Failed to initialize mempalace in ${dir}:`, error);
  }
}

export async function wakeUp(wing: string): Promise<string | null> {
  try {
    const { stdout } = await executeMempalace(['wake-up', '--wing', wing]);
    return stdout;
  } catch (error) {
    console.warn(`Failed to wake up mempalace:`, error);
    return null;
  }
}

export async function mine(dir: string, mode: string, wing: string): Promise<void> {
  try {
    await executeMempalace(['mine', dir, '--mode', mode, '--wing', wing]);
  } catch (error) {
    console.warn(`Failed to mine mempalace:`, error);
  }
}

export function mineSync(dir: string, mode: string, wing: string): void {
  const options = { timeout: 5000 };
  const commands = [
    { cmd: 'mempalace', args: ['mine', dir, '--mode', mode, '--wing', wing] },
    { cmd: 'python3', args: ['-m', 'mempalace', 'mine', dir, '--mode', mode, '--wing', wing] },
    { cmd: 'python', args: ['-m', 'mempalace', 'mine', dir, '--mode', mode, '--wing', wing] },
  ];

  for (const { cmd, args } of commands) {
    try {
      execa.sync(cmd, args, options);
      return;
    } catch (error: any) {
      if (error.timedOut) break;
    }
  }
}
