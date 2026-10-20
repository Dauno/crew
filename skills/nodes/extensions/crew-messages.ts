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

  const dispatchClaimed = () => {
    if (stopped || !claimedMessage || !context?.isIdle()) return;
    const message = claimedMessage;
    try {
      pi.sendMessage({
        customType: "crew-message",
        content: formatMessage(message),
        display: true,
        details: { id: message.id, from: message.from },
      }, { triggerTurn: true });
      claimedMessage = undefined;
    } catch (error) {
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

  pi.on("session_start", async (_event, ctx) => {
    if (timer) clearTimeout(timer);
    timer = undefined;
    context = ctx;
    stopped = false;
    schedule();
  });

  pi.on("session_shutdown", async () => {
    stopped = true;
    context = undefined;
    if (timer) clearTimeout(timer);
    timer = undefined;
  });
}
