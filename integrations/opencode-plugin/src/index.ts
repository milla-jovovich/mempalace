import { wakeUp, mine, mineSync, isInitialized, initialize } from './mempalace-cli.js';
import { StateManager } from './state.js';
import { getWingFromPath, isEmptyWorkspace } from './utils.js';

export default async function mempalacePlugin(input: any, options?: any): Promise<any> {
  const dir = input.worktree || input.directory || process.cwd();
  const wing = getWingFromPath(dir);
  const threshold = (options?.threshold as number) || 15;
  const stateManager = new StateManager(threshold);

  let initializationDone = false;
  let isInitializing = false;

  const ensureInitialized = async (): Promise<'ready' | 'initializing' | 'empty'> => {
    if (isEmptyWorkspace(dir)) {
      return 'empty';
    }

    if (initializationDone) {
      return 'ready';
    }

    if (isInitializing) {
      return 'initializing';
    }

    const initialized = await isInitialized(dir);
    if (initialized) {
      initializationDone = true;
      return 'ready';
    }

    isInitializing = true;
    initialize(dir)
      .then(() => {
        initializationDone = true;
      })
      .catch((e) => {
        console.warn('Background initialization failed:', e);
      })
      .finally(() => {
        isInitializing = false;
      });

    return 'initializing';
  };

  const MAX_MEMORY_LENGTH = 4000;

  let isFlushing = false;
  const flushDirtySessions = () => {
    if (isFlushing) return;
    isFlushing = true;
    const dirtySessions = stateManager.getDirtySessions();
    if (dirtySessions.length > 0) {
      mineSync(dir, 'convos', wing);
      for (const id of dirtySessions) {
        stateManager.resetCount(id);
      }
    }
  };

  process.on('exit', flushDirtySessions);
  process.on('SIGINT', () => {
    flushDirtySessions();
    process.exit(130);
  });
  process.on('SIGTERM', () => {
    flushDirtySessions();
    process.exit(143);
  });

  return {
    event: async ({ event }: { event: any }) => {
      if (
        event.type === 'session.idle' ||
        event.type === 'session.deleted' ||
        (event.type === 'session.status' && event.properties?.status?.type === 'idle')
      ) {
        const sessionID = event.properties?.sessionID || event.properties?.info?.id;
        if (sessionID && stateManager.hasPendingMessages(sessionID)) {
          if (!stateManager.acquireMiningLock(sessionID)) return;

          const state = await ensureInitialized();
          if (state !== 'ready') {
            stateManager.releaseMiningLock(sessionID);
            return;
          }

          setTimeout(() => {
            mine(dir, 'convos', wing)
              .catch(() => {})
              .finally(() => {
                stateManager.releaseMiningLock(sessionID);
                stateManager.resetCount(sessionID);
              });
          }, 2000);
        }
      }
    },

    'experimental.session.compacting': async (
      _: any,
      output: { context: string[]; prompt?: string },
    ) => {
      const state = await ensureInitialized();
      if (state === 'empty') {
        output.context.push(
          '[MemPalace]: This environment has no memory yet. Please proceed with standard logic.',
        );
        return;
      }
      if (state === 'initializing') {
        output.context.push(
          '[MemPalace]: The memory system is being built asynchronously in the background. The current response will not include historical memory context.',
        );
        return;
      }

      const memory = await wakeUp(wing);
      if (memory) {
        const truncatedMemory =
          memory.length > MAX_MEMORY_LENGTH
            ? memory.substring(0, MAX_MEMORY_LENGTH) + '\n...[Memory Truncated]'
            : memory;
        output.context.push(truncatedMemory);
      }
    },

    'experimental.chat.system.transform': async (_: any, output: { system: string[] }) => {
      const state = await ensureInitialized();
      if (state === 'empty') {
        output.system.push(
          '[MemPalace]: This environment has no memory yet. Please proceed with standard logic.',
        );
        return;
      }
      if (state === 'initializing') {
        output.system.push(
          '[MemPalace]: The memory system is being built asynchronously in the background. The current response will not include historical memory context.',
        );
        return;
      }

      const memory = await wakeUp(wing);
      if (memory) {
        const truncatedMemory =
          memory.length > MAX_MEMORY_LENGTH
            ? memory.substring(0, MAX_MEMORY_LENGTH) + '\n...[Memory Truncated]'
            : memory;
        output.system.push(truncatedMemory);
      }
    },

    'chat.message': async ({ sessionID }: { sessionID: string }) => {
      if (stateManager.incrementAndCheck(sessionID)) {
        if (!stateManager.acquireMiningLock(sessionID)) return;

        const state = await ensureInitialized();
        if (state !== 'ready') {
          stateManager.releaseMiningLock(sessionID);
          return;
        }

        // Delay to protect TTFT
        setTimeout(() => {
          mine(dir, 'convos', wing)
            .catch(() => {})
            .finally(() => {
              stateManager.releaseMiningLock(sessionID);
            });
        }, 2000);
      }
    },
  };
}
