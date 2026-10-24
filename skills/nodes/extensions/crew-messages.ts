import { execFile } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type {
  ExtensionAPI,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";

interface CrewMessage {
  id: string;
  from: string;
  text: string;
}

interface CrewEntry {
  type: string;
  id?: string;
  parentId?: string | null;
  timestamp?: string;
  customType?: string;
  content?: unknown;
  display?: boolean;
  details?: unknown;
}

interface ReceiverRuntime {
  context: ExtensionContext;
  piSessionId: string;
  sessionFile?: string;
  crewSessionId: string;
  inbox?: string;
  compacting: boolean;
  runActive: boolean;
  polling: boolean;
  claimedMessage?: CrewMessage;
  inFlightMessageId?: string;
  candidate?: CrewMessage;
  dispatchAttempts: number;
  lastDispatchAt: number;
  ackAttempts: number;
  ackRetryAt: number;
  ackInFlight: boolean;
  timer?: ReturnType<typeof setTimeout>;
}

const POLL_INTERVAL_MS = 500;
const DISPATCH_RETRY_MS = 1_000;
const ACK_RETRY_MS = 500;
const MAX_DISPATCH_ATTEMPTS = 3;
const MAX_ACK_ATTEMPTS = 3;

const formatMessage = (message: CrewMessage) => [
  `CREW_MESSAGE_ID: ${message.id}`,
  `CREW_FROM: ${message.from}`,
  "",
  message.text,
].join("\n");

function hasExactDetails(value: unknown, message: CrewMessage): boolean {
  if (!value || typeof value !== "object") return false;
  const details = value as Record<string, unknown>;
  return Object.keys(details).length === 2 &&
    details.id === message.id && details.from === message.from;
}

function isExactCrewEntry(
  value: unknown,
  message: CrewMessage,
): value is CrewEntry {
  if (!value || typeof value !== "object") return false;
  const entry = value as CrewEntry;
  return entry.type === "custom_message" &&
    entry.customType === "crew-message" &&
    entry.content === formatMessage(message) &&
    entry.display === true &&
    hasExactDetails(entry.details, message);
}

export default function (pi: ExtensionAPI) {
  let runtime: ReceiverRuntime | undefined;

  const isCurrent = (owner: ReceiverRuntime) => runtime === owner;

  const isSamePiSession = (owner: ReceiverRuntime) =>
    isCurrent(owner) &&
    owner.context.sessionManager.getSessionId() === owner.piSessionId &&
    owner.context.sessionManager.getSessionFile() === owner.sessionFile;

  const receivedPath = (owner: ReceiverRuntime, messageId: string) =>
    owner.inbox && join(owner.inbox, "received", `${messageId}.json`);

  const wasReceived = (owner: ReceiverRuntime, messageId: string) => {
    const path = receivedPath(owner, messageId);
    return Boolean(path && existsSync(path));
  };

  const clearClaim = (owner: ReceiverRuntime) => {
    owner.claimedMessage = undefined;
    owner.inFlightMessageId = undefined;
    owner.candidate = undefined;
    owner.dispatchAttempts = 0;
    owner.lastDispatchAt = 0;
    owner.ackAttempts = 0;
    owner.ackRetryAt = 0;
    owner.ackInFlight = false;
  };

  const schedule = (owner: ReceiverRuntime) => {
    if (!isCurrent(owner) || owner.timer) return;
    owner.timer = setTimeout(() => {
      owner.timer = undefined;
      poll(owner);
    }, POLL_INTERVAL_MS);
  };

  const commandEnvironment = (owner: ReceiverRuntime) => {
    const env = { ...process.env };
    env.CREW_SESSION_ID = owner.crewSessionId;
    if (owner.inbox) env.CREW_INBOX = owner.inbox;
    return env;
  };

  const persistedReceipt = (owner: ReceiverRuntime, message: CrewMessage) => {
    if (!isSamePiSession(owner) || !owner.sessionFile) return false;

    const branchEntry = owner.context.sessionManager.getBranch().find(
      (entry) => isExactCrewEntry(entry, message),
    );
    if (!branchEntry?.id) return false;

    let lines: string[];
    try {
      lines = readFileSync(owner.sessionFile, "utf8").split(/\r?\n/)
        .filter((line) => line.length > 0);
    } catch {
      return false;
    }
    if (lines.length < 2) return false;

    let header: unknown;
    try {
      header = JSON.parse(lines[0]);
    } catch {
      return false;
    }
    if (!header || typeof header !== "object" ||
        (header as Record<string, unknown>).type !== "session" ||
        (header as Record<string, unknown>).id !== owner.piSessionId) {
      return false;
    }

    for (const line of lines.slice(1)) {
      let entry: unknown;
      try {
        entry = JSON.parse(line);
      } catch {
        continue;
      }
      if (!entry || typeof entry !== "object" ||
          (entry as Record<string, unknown>).id !== branchEntry.id) {
        continue;
      }
      const persisted = entry as CrewEntry;
      return persisted.parentId === branchEntry.parentId &&
        persisted.timestamp === branchEntry.timestamp &&
        isExactCrewEntry(persisted, message);
    }
    return false;
  };

  const acknowledge = (owner: ReceiverRuntime, message: CrewMessage) => {
    if (!isSamePiSession(owner) || owner.ackInFlight ||
        owner.ackAttempts >= MAX_ACK_ATTEMPTS ||
        Date.now() < owner.ackRetryAt) {
      return;
    }
    if (!persistedReceipt(owner, message)) return;
    if (wasReceived(owner, message.id)) {
      clearClaim(owner);
      return;
    }

    owner.ackInFlight = true;
    owner.ackAttempts++;
    execFile("crew-nodes", ["ack", message.id], {
      encoding: "utf8",
      maxBuffer: 1024 * 1024,
      env: commandEnvironment(owner),
    }, (error) => {
      if (!isSamePiSession(owner) ||
          owner.claimedMessage?.id !== message.id) return;
      owner.ackInFlight = false;
      if (wasReceived(owner, message.id)) {
        clearClaim(owner);
      } else {
        if (error) {
          console.error(
            "crew Pi receiver could not acknowledge a persisted message",
            error,
          );
        }
        owner.ackRetryAt = Date.now() + ACK_RETRY_MS;
      }
      schedule(owner);
    });
  };

  const dispatchClaimed = (owner: ReceiverRuntime) => {
    const message = owner.claimedMessage;
    if (!isCurrent(owner) || !message || owner.candidate ||
        owner.dispatchAttempts >= MAX_DISPATCH_ATTEMPTS) return;
    const busy = owner.runActive;
    if (owner.compacting || (!busy && !owner.context.isIdle())) return;
    if (owner.inFlightMessageId) return;

    owner.dispatchAttempts++;
    owner.inFlightMessageId = message.id;
    owner.lastDispatchAt = Date.now();
    try {
      pi.sendMessage({
        customType: "crew-message",
        content: formatMessage(message),
        display: true,
        details: { id: message.id, from: message.from },
      }, busy
        ? { deliverAs: "steer", triggerTurn: true }
        : { triggerTurn: true });
    } catch (error) {
      if (isCurrent(owner) && owner.inFlightMessageId === message.id) {
        owner.inFlightMessageId = undefined;
      }
      console.error(
        "crew Pi receiver could not dispatch a mailbox message",
        error,
      );
    }
  };

  const poll = (owner: ReceiverRuntime) => {
    if (!isSamePiSession(owner) || owner.polling) return;

    const message = owner.claimedMessage;
    if (message) {
      if (wasReceived(owner, message.id)) {
        clearClaim(owner);
      } else if (owner.candidate) {
        acknowledge(owner, owner.candidate);
        schedule(owner);
        return;
      } else if (owner.inFlightMessageId === message.id) {
        const runStillActive = owner.runActive || !owner.context.isIdle();
        const retryReady =
          Date.now() - owner.lastDispatchAt >= DISPATCH_RETRY_MS;
        if (runStillActive || !retryReady) {
          schedule(owner);
          return;
        }
        owner.inFlightMessageId = undefined;
      } else {
        dispatchClaimed(owner);
        schedule(owner);
        return;
      }
    }

    owner.polling = true;
    execFile("crew-nodes", ["_mailbox", "claim"], {
      encoding: "utf8",
      maxBuffer: 1024 * 1024,
      env: commandEnvironment(owner),
    }, (error, stdout) => {
      owner.polling = false;
      if (!isSamePiSession(owner)) return;
      if (error) {
        console.error(
          "crew Pi receiver could not claim a mailbox message",
          error,
        );
      }
      if (!error && stdout.trim()) {
        try {
          const claimed = JSON.parse(stdout) as CrewMessage;
          if (claimed.id && claimed.from &&
              typeof claimed.text === "string") {
            owner.claimedMessage = claimed;
            owner.inFlightMessageId = undefined;
            owner.candidate = undefined;
            owner.dispatchAttempts = 0;
            owner.lastDispatchAt = 0;
            owner.ackAttempts = 0;
            owner.ackRetryAt = 0;
            owner.ackInFlight = false;
            dispatchClaimed(owner);
          }
        } catch (parseError) {
          console.error(
            "crew Pi receiver could not parse a mailbox message",
            parseError,
          );
        }
      }
      schedule(owner);
    });
  };

  pi.on("message_end", async (event) => {
    const owner = runtime;
    const message = event.message;
    const claimed = owner?.claimedMessage;
    if (!owner || !claimed || !isSamePiSession(owner) ||
        message.role !== "custom" || message.customType !== "crew-message" ||
        owner.inFlightMessageId !== claimed.id ||
        !isExactCrewEntry({
          type: "custom_message",
          customType: message.customType,
          content: message.content,
          display: message.display,
          details: message.details,
        }, claimed)) {
      return;
    }
    owner.candidate = claimed;
    schedule(owner);
  });

  pi.on("agent_start", async () => {
    if (runtime) runtime.runActive = true;
  });
  // A steer without a matching message_end may have been discarded on abort.
  // Keep idle fallback, but never resend a confirmed candidate.
  pi.on("agent_settled", async () => {
    const owner = runtime;
    if (!owner) return;
    owner.runActive = false;
    owner.compacting = false;
    if (owner.claimedMessage && !owner.candidate) {
      owner.inFlightMessageId = undefined;
      owner.lastDispatchAt = 0;
    }
    schedule(owner);
  });
  pi.on("session_before_compact", async () => {
    if (runtime) runtime.compacting = true;
  });
  pi.on("session_compact", async () => {
    if (runtime) runtime.compacting = false;
  });
  pi.on("session_compact_failed", async () => {
    if (runtime) runtime.compacting = false;
  });

  pi.on("session_start", async (_event, context) => {
    if (runtime?.timer) clearTimeout(runtime.timer);
    runtime = {
      context,
      piSessionId: context.sessionManager.getSessionId(),
      sessionFile: context.sessionManager.getSessionFile() ?? undefined,
      crewSessionId: process.env.CREW_SESSION_ID ?? "",
      inbox: process.env.CREW_INBOX,
      compacting: false,
      runActive: false,
      polling: false,
      dispatchAttempts: 0,
      lastDispatchAt: 0,
      ackAttempts: 0,
      ackRetryAt: 0,
      ackInFlight: false,
    };
    schedule(runtime);
  });

  pi.on("session_shutdown", async () => {
    if (runtime?.timer) clearTimeout(runtime.timer);
    runtime = undefined;
  });
}
