import { execFile } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

interface CrewMessage {
  id: string;
  from: string;
  text: string;
}

const formatMessage = (message: CrewMessage) =>
  `CREW_MESSAGE_ID: ${message.id}\nCREW_FROM: ${message.from}\n\n${message.text}`;

export default function (pi: ExtensionAPI) {
  let context: { isIdle(): boolean } | undefined;
  let stopped = true;
  let compacting = false;
  let runActive = false;
  let inFlightMessageId: string | undefined;
  let polling = false;
  let claimedMessage: CrewMessage | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const schedule = () => {
    if (stopped || timer) return;
    timer = setTimeout(() => {
      timer = undefined;
      poll();
    }, 500);
  };

  const dispatchClaimed = async () => {
    if (stopped || !claimedMessage || !context) return;
    const message = claimedMessage;
    const busy = runActive;
    if (compacting || (!busy && !context.isIdle())) return;
    if (busy && inFlightMessageId) return;
    try {
      if (busy) inFlightMessageId = message.id;
      pi.sendMessage({
        customType: "crew-message",
        content: formatMessage(message),
        display: true,
        details: { id: message.id, from: message.from },
      }, busy
        ? { deliverAs: "steer", triggerTurn: true }
        : { triggerTurn: true });
      if (!busy) claimedMessage = undefined;
    } catch (error) {
      if (busy) inFlightMessageId = undefined;
      console.error("crew Pi receiver could not dispatch a mailbox message", error);
    }
  };

  const poll = () => {
    if (stopped || polling || !context) return;
    if (claimedMessage) {
      dispatchClaimed();
      schedule();
      return;
    }
    polling = true;
    execFile("crew-nodes", ["_mailbox", "claim"], {
      encoding: "utf8",
      maxBuffer: 1024 * 1024,
    }, (error, stdout) => {
      polling = false;
      if (error) {
        console.error("crew Pi receiver could not claim a mailbox message", error);
      }
      if (!stopped && !error && stdout.trim()) {
        try {
          const message = JSON.parse(stdout) as CrewMessage;
          if (message.id && message.from && typeof message.text === "string") {
            claimedMessage = message;
            dispatchClaimed();
          }
        } catch (parseError) {
          console.error("crew Pi receiver could not parse a mailbox message", parseError);
        }
      }
      schedule();
    });
  };

  pi.on("message_end", async (event) => {
    const message = event.message;
    if (message.role === "custom" && message.customType === "crew-message" &&
        message.details?.id === inFlightMessageId) {
      claimedMessage = undefined;
      inFlightMessageId = undefined;
    }
  });

  pi.on("agent_start", async () => { runActive = true; });
  // A queued steer may survive an unusual error exit and later duplicate fallback.
  // At-least-once delivery prevents silent loss; acknowledgements are idempotent.
  pi.on("agent_settled", async () => {
    runActive = false;
    compacting = false;
    if (inFlightMessageId) inFlightMessageId = undefined;
    schedule();
  });
  pi.on("session_before_compact", async () => { compacting = true; });
  pi.on("session_compact", async () => { compacting = false; });
  pi.on("session_compact_failed", async () => { compacting = false; });

  pi.on("session_start", async (_event, ctx) => {
    if (timer) clearTimeout(timer);
    timer = undefined;
    context = ctx;
    compacting = false;
    runActive = false;
    inFlightMessageId = undefined;
    stopped = false;
    schedule();
  });

  pi.on("session_shutdown", async () => {
    stopped = true;
    compacting = false;
    runActive = false;
    inFlightMessageId = undefined;
    context = undefined;
    if (timer) clearTimeout(timer);
    timer = undefined;
  });
}
