"""No-inference lifecycle regression tests for the Pi mailbox extension."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MAILBOX_SCRIPT = ROOT / "skills/nodes/scripts/mailbox.py"
SPEC = importlib.util.spec_from_file_location("crew_mailbox_for_pi", MAILBOX_SCRIPT)
mailbox = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mailbox)

SENDER = "11111111-1111-4111-8111-111111111111"
RECIPIENT = "22222222-2222-4222-8222-222222222222"

JS_SETUP = r'''import {
  appendFileSync, readFileSync, writeFileSync,
} from "node:fs";
import { pathToFileURL } from "node:url";
import { execFileSync } from "node:child_process";
const { default: extension } = await import(
  pathToFileURL(process.env.CREW_EXTENSION_PATH).href
);
const handlers = {};
const sent = [];
let sendAttempts = 0;
const failSends = Number(process.env.CREW_FAIL_SENDS || 0);
let compacting = false;
let streaming = false;
let otherBusy = false;
const sessionFile = process.env.CREW_PI_SESSION_FILE;
const sessionId = process.env.CREW_PI_SESSION_ID;
const header = {
  type: "session", version: 3, id: sessionId,
  timestamp: "2026-10-24T00:00:00.000Z", cwd: process.cwd(),
};
const branch = [];
let persisted = process.env.CREW_PI_NEW_SESSION !== "1";
const writeSession = (headerId = sessionId) => {
  const rows = [{ ...header, id: headerId }, ...branch];
  const jsonl = rows.map((row) => JSON.stringify(row)).join("\n") + "\n";
  writeFileSync(sessionFile, jsonl);
};
if (persisted) {
  branch.push({
    type: "message", id: "initial-user", parentId: null,
    timestamp: header.timestamp,
    message: {
      role: "user", content: "synthetic initial prompt", timestamp: 0,
    },
  });
  writeSession();
}
const sessionManager = {
  getSessionId: () => sessionId,
  getSessionFile: () => sessionFile,
  getBranch: () => branch.slice(),
};
const pi = {
  on: (event, handler) => { handlers[event] = handler; },
  sendMessage: (message, delivery) => {
    sendAttempts++;
    if (sendAttempts <= failSends) throw new Error("simulated send failure");
    sent.push({ message, delivery });
  },
};
extension(pi);
const context = {
  isIdle: () => !streaming && !compacting && !otherBusy,
  sessionManager,
};
const delay = (milliseconds) => new Promise((resolve) =>
  setTimeout(resolve, milliseconds));
const waitFor = async (predicate, message, attempts = 40) => {
  for (let attempt = 0; attempt < attempts; attempt++) {
    if (predicate()) return;
    await delay(125);
  }
  throw new Error(message);
};
const waitForClaim = async () => {
  await waitFor(() => {
    try {
      return Boolean(JSON.parse(readFileSync(
        `${process.env.CREW_INBOX}/.delivery.json`, "utf8")).id);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      return false;
    }
  }, "extension did not claim the pending message");
};
const completeMessageEnd = async (index, { persist = true } = {}) => {
  const message = { role: "custom", ...sent[index].message };
  await handlers.message_end({ message });
  const entry = {
    type: "custom_message", id: `custom-entry-${branch.length}`,
    parentId: branch.at(-1)?.id ?? null, timestamp: header.timestamp,
    customType: message.customType, content: message.content,
    display: message.display, details: message.details,
  };
  branch.push(entry);
  if (persist && persisted) {
    appendFileSync(sessionFile, `${JSON.stringify(entry)}\n`);
  }
  return entry;
};
const persistFirstAssistant = () => {
  branch.push({
    type: "message", id: `assistant-entry-${branch.length}`,
    parentId: branch.at(-1)?.id ?? null, timestamp: header.timestamp,
    message: {
      role: "assistant", content: "synthetic response", timestamp: 1,
    },
  });
  persisted = true;
  writeSession();
};
const isReceived = (messageId) => {
  try {
    readFileSync(`${process.env.CREW_INBOX}/received/${messageId}.json`);
    return true;
  } catch (error) {
    if (error.code === "ENOENT") return false;
    throw error;
  }
};
const markerId = () => JSON.parse(readFileSync(
  `${process.env.CREW_INBOX}/.delivery.json`, "utf8",
)).id;
const ackAttempts = () => {
  try { return Number(readFileSync(process.env.CREW_ACK_COUNTER, "utf8")); }
  catch (error) { if (error.code === "ENOENT") return 0; throw error; }
};
await handlers.session_start({}, context);
'''


@unittest.skipUnless(shutil.which("node"), "node is required for extension tests")
class PiExtensionLifecycleTest(unittest.TestCase):
    def runtime(
        self, count=1, fail_first_send=False, *, new_session=False,
        fail_sends=None, fail_acks=0, delay_ack_ms=0, delay_claim_ms=0,
    ):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        home = base / "crew"
        sender = mailbox.initialize_session(SENDER, cli="pi", home=home)
        receiver = mailbox.initialize_session(RECIPIENT, cli="pi", home=home)
        tools = base / "tools"
        tools.mkdir()
        crew_nodes = tools / "crew-nodes"
        ack_counter = base / "ack-count"
        crew_nodes.write_text(
            f"#!{sys.executable}\n"
            "import os, pathlib, subprocess, sys, time\n"
            "if sys.argv[1:2] == ['ack']:\n"
            "  counter = pathlib.Path(os.environ['CREW_ACK_COUNTER'])\n"
            "  try: attempts = int(counter.read_text())\n"
            "  except FileNotFoundError: attempts = 0\n"
            "  attempts += 1\n"
            "  counter.write_text(str(attempts))\n"
            "  if attempts <= int(os.environ.get('CREW_FAIL_ACKS', '0')):\n"
            "    raise SystemExit(7)\n"
            "if sys.argv[1:3] == ['_mailbox', 'claim']:\n"
            "  delay_ms = int(os.environ.get('CREW_DELAY_CLAIM_MS', '0'))\n"
            "  time.sleep(delay_ms / 1000)\n"
            "result = subprocess.run(\n"
            "  ['bash',\n"
            f"    {str(ROOT / 'bin/crew-nodes')!r}, *sys.argv[1:]],\n"
            "  check=False,\n"
            ")\n"
            "if sys.argv[1:2] == ['ack']:\n"
            "  delay_ms = int(os.environ.get('CREW_DELAY_ACK_MS', '0'))\n"
            "  time.sleep(delay_ms / 1000)\n"
            "raise SystemExit(result.returncode)\n"
        )
        crew_nodes.chmod(0o700)
        with mock.patch.dict(os.environ, {
            "CREW_HOME": str(home),
            "CREW_SESSION_ID": SENDER,
            "CREW_INBOX": str(sender),
            "CREW_CLI": "pi",
        }):
            ids = [mailbox.publish_message(
                RECIPIENT, f"test message {index}", home=home,
            ) for index in range(count)]

        pi_session_dir = base / "pi-sessions"
        pi_session_dir.mkdir()
        pi_session_id = "55555555-5555-4555-8555-555555555555"
        if fail_sends is None:
            fail_sends = 1 if fail_first_send else 0
        env = os.environ.copy()
        env.update({
            "CREW_HOME": str(home),
            "CREW_SESSION_ID": RECIPIENT,
            "CREW_INBOX": str(receiver),
            "CREW_CLI": "pi",
            "CREW_NODES_SCRIPT": str(ROOT / "skills/nodes/scripts/nodes.sh"),
            "CREW_EXTENSION_PATH": str(
                ROOT / "skills/nodes/extensions/crew-messages.ts"
            ),
            "CREW_MESSAGE_IDS": json.dumps(ids),
            "CREW_FAIL_SENDS": str(fail_sends),
            "CREW_FAIL_ACKS": str(fail_acks),
            "CREW_DELAY_ACK_MS": str(delay_ack_ms),
            "CREW_DELAY_CLAIM_MS": str(delay_claim_ms),
            "CREW_ACK_COUNTER": str(ack_counter),
            "CREW_PI_SESSION_DIR": str(pi_session_dir),
            "CREW_PI_SESSION_FILE": str(pi_session_dir / "session.jsonl"),
            "CREW_PI_SESSION_ID": pi_session_id,
            "CREW_PI_NEW_SESSION": "1" if new_session else "0",
            "PATH": (
                str(tools) + os.pathsep + str(ROOT / "bin")
                + os.pathsep + os.environ["PATH"]
            ),
        })
        return {"temporary": temporary, "env": env, "ids": ids,
                "receiver": receiver, "ack_counter": ack_counter}

    def received_path(self, runtime, message_id):
        return runtime["receiver"] / "received" / f"{message_id}.json"

    def run_script(self, runtime, script):
        result = subprocess.run(
            [shutil.which("node"), "--experimental-strip-types",
             "--input-type=module", "-e", JS_SETUP + script],
            cwd=ROOT,
            env=runtime["env"],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_busy_agent_receives_one_steer_without_periodic_resends(self):
        runtime = self.runtime()
        self.run_script(runtime, r'''const [messageId] = JSON.parse(process.env.CREW_MESSAGE_IDS);
streaming = true;
await handlers.agent_start();
await waitForClaim();
await waitFor(() => sent.length === 1, "busy extension did not steer");
if (sent[0].delivery.deliverAs !== "steer" ||
    sent[0].delivery.triggerTurn !== true) {
  throw new Error("busy message did not use steer delivery");
}
await delay(900);
if (sent.length !== 1) throw new Error("busy extension duplicated a queued steer");
if (!sent[0].message.content.includes(messageId)) {
  throw new Error("dispatched message lost its acknowledgement ID");
}
await handlers.session_shutdown();
''')

    def test_idle_messages_auto_ack_after_persistence(self):
        runtime = self.runtime(count=2)
        first_id, second_id = runtime["ids"]
        self.run_script(runtime, r'''const [firstId, secondId] =
  JSON.parse(process.env.CREW_MESSAGE_IDS);
await waitFor(
  () => sent.length === 1,
  "first idle message was not delivered",
);
await completeMessageEnd(0);
await waitFor(
  () => sent.length === 2,
  "second message did not follow persisted receipt",
);
if (!sent[1].message.content.includes(secondId)) {
  throw new Error("wrong second message");
}
await completeMessageEnd(1);
await waitFor(
  () => isReceived(secondId),
  "second message was not automatically acknowledged",
);
if (!sent[0].message.content.includes(firstId)) {
  throw new Error("wrong first message");
}
await handlers.session_shutdown();
''')
        self.assertTrue(self.received_path(runtime, first_id).is_file())

    def test_busy_messages_auto_ack_after_persistence(self):
        runtime = self.runtime(count=2)
        first_id, second_id = runtime["ids"]
        self.run_script(runtime, r'''const [firstId, secondId] =
  JSON.parse(process.env.CREW_MESSAGE_IDS);
streaming = true;
await handlers.agent_start();
await waitFor(
  () => sent.length === 1,
  "first message was not steered",
);
await completeMessageEnd(0);
await waitFor(
  () => sent.length === 2,
  "second message did not follow persisted steer",
);
if (sent[1].delivery.deliverAs !== "steer" ||
    !sent[1].message.content.includes(secondId)) {
  throw new Error("second busy message was not steered correctly");
}
await completeMessageEnd(1);
await waitFor(
  () => isReceived(secondId),
  "second busy message was not automatically acknowledged",
);
if (!sent[0].message.content.includes(firstId)) {
  throw new Error("wrong first message");
}
streaming = false;
await handlers.agent_settled();
await handlers.session_shutdown();
''')
        self.assertTrue(self.received_path(runtime, first_id).is_file())

    def test_custom_first_message_waits_for_persistence(self):
        runtime = self.runtime(count=2, new_session=True)
        first_id, second_id = runtime["ids"]
        self.run_script(runtime, r'''const [firstId, secondId] =
  JSON.parse(process.env.CREW_MESSAGE_IDS);
await waitFor(
  () => sent.length === 1,
  "first custom message was not delivered",
);
await completeMessageEnd(0, { persist: false });
await delay(800);
if (sent.length !== 1) {
  throw new Error("unpersisted custom-first message was reinjected");
}
if (markerId() !== firstId) {
  throw new Error(
    "unpersisted first message did not retain the mailbox hold",
  );
}
if (isReceived(firstId)) {
  throw new Error("custom-first message was acknowledged before persistence");
}
persistFirstAssistant();
await waitFor(
  () => sent.length === 2,
  "session flush did not release the next message",
);
if (!sent[1].message.content.includes(secondId)) {
  throw new Error("wrong next message");
}
await handlers.session_shutdown();
''')
        self.assertTrue(self.received_path(runtime, first_id).is_file())

    def test_acknowledgement_failure_retries_without_reinjection(self):
        runtime = self.runtime(count=2, fail_acks=3)
        first_id, second_id = runtime["ids"]
        self.run_script(runtime, r'''const [firstId, secondId] =
  JSON.parse(process.env.CREW_MESSAGE_IDS);
await waitFor(
  () => sent.length === 1,
  "first message was not delivered",
);
await completeMessageEnd(0);
await waitFor(
  () => ackAttempts() === 3,
  "acknowledgement was not retried three times",
);
await delay(800);
if (ackAttempts() !== 3) throw new Error("ack retry exceeded its bound");
if (sent.length !== 1) {
  throw new Error("confirmed message was reinjected after ack failure");
}
try {
  readFileSync(`${process.env.CREW_INBOX}/received/${firstId}.json`);
  throw new Error("failed acknowledgements unexpectedly moved the message");
} catch (error) { if (error.code !== "ENOENT") throw error; }
execFileSync("crew-nodes", ["ack", firstId]);
await waitFor(
  () => sent.length === 2,
  "manual recovery did not release next message",
);
if (!sent[1].message.content.includes(secondId)) {
  throw new Error("wrong next message");
}
await handlers.session_shutdown();
''')
        self.assertTrue(self.received_path(runtime, first_id).is_file())
        self.assertEqual(runtime["ack_counter"].read_text(), "4")

    def test_transient_ack_failure_recovers_automatically(self):
        runtime = self.runtime(count=2, fail_acks=1)
        first_id, second_id = runtime["ids"]
        self.run_script(runtime, r'''const [firstId, secondId] =
  JSON.parse(process.env.CREW_MESSAGE_IDS);
await waitFor(
  () => sent.length === 1,
  "first message was not delivered",
);
await completeMessageEnd(0);
await waitFor(
  () => ackAttempts() === 2,
  "transient acknowledgement failure was not retried",
);
await waitFor(
  () => sent.length === 2,
  "automatic ack retry did not release next message",
);
if (!sent[1].message.content.includes(secondId)) {
  throw new Error("wrong next message");
}
await handlers.session_shutdown();
''')
        self.assertTrue(self.received_path(runtime, first_id).is_file())
        self.assertEqual(runtime["ack_counter"].read_text(), "2")

    def test_dispatch_failure_retries_only_to_the_bound(self):
        runtime = self.runtime(fail_sends=99)
        first_id = runtime["ids"][0]
        self.run_script(runtime, r'''await waitForClaim();
await waitFor(
  () => sendAttempts === 3,
  "failed injection was not retried to its bound",
);
await delay(1_200);
if (sendAttempts !== 3) throw new Error("injection retry exceeded its bound");
if (sent.length !== 0) {
  throw new Error("failed injection was recorded as delivered");
}
if (markerId() !== JSON.parse(process.env.CREW_MESSAGE_IDS)[0]) {
  throw new Error("failed injection lost its durable hold");
}
await handlers.session_shutdown();
''')
        self.assertFalse(self.received_path(runtime, first_id).exists())

    def test_persistence_requires_exact_session_and_message(self):
        runtime = self.runtime(new_session=True)
        first_id = runtime["ids"][0]
        self.run_script(runtime, r'''const [firstId] =
  JSON.parse(process.env.CREW_MESSAGE_IDS);
await waitFor(
  () => sent.length === 1,
  "first custom message was not delivered",
);
const wrongDetails = {
  ...sent[0].message, role: "custom",
  details: { id: firstId, from: "33333333-3333-4333-8333-333333333333" },
};
await handlers.message_end({ message: wrongDetails });
await handlers.message_end({ message: {
  ...sent[0].message, role: "custom",
  content: `${sent[0].message.content} altered`,
} });
await handlers.message_end({ message: {
  ...sent[0].message, role: "custom",
} });
branch.push({
  type: "custom_message", id: "custom-entry-wrong", parentId: null,
  timestamp: header.timestamp, customType: "crew-message",
  content: sent[0].message.content, display: true,
  details: sent[0].message.details,
});
branch.push({
  type: "message", id: "assistant-entry-wrong",
  parentId: "custom-entry-wrong",
  timestamp: header.timestamp,
  message: { role: "assistant", content: "synthetic response", timestamp: 1 },
});
persisted = true;
writeSession("66666666-6666-4666-8666-666666666666");
await delay(800);
if (ackAttempts() !== 0) {
  throw new Error("mismatched receipt was acknowledged");
}
writeSession();
await waitFor(
  () => isReceived(firstId),
  "matching persisted receipt was not acknowledged",
);
await handlers.session_shutdown();
''')

    def test_out_of_band_ack_before_persistence_releases_next_message(self):
        runtime = self.runtime(count=2, new_session=True)
        first_id, second_id = runtime["ids"]
        self.run_script(runtime, r'''const [firstId, secondId] =
  JSON.parse(process.env.CREW_MESSAGE_IDS);
await waitFor(
  () => sent.length === 1,
  "first custom message was not delivered",
);
await completeMessageEnd(0, { persist: false });
execFileSync("crew-nodes", ["ack", firstId]);
await waitFor(
  () => sent.length === 2,
  "out-of-band ack did not release next message",
);
if (!sent[1].message.content.includes(secondId)) {
  throw new Error("wrong next message");
}
await handlers.session_shutdown();
''')
        self.assertTrue(self.received_path(runtime, first_id).is_file())

    def test_old_ack_callback_does_not_mutate_replacement_session(self):
        runtime = self.runtime(count=2, delay_ack_ms=1_500)
        first_id, second_id = runtime["ids"]
        self.run_script(runtime, r'''const [firstId, secondId] =
  JSON.parse(process.env.CREW_MESSAGE_IDS);
await waitFor(
  () => sent.length === 1,
  "first message was not delivered",
);
await completeMessageEnd(0);
await waitFor(
  () => isReceived(firstId),
  "ack command did not persist the first receipt",
);
await handlers.session_shutdown();
const nextSession = "66666666-6666-4666-8666-666666666666";
const nextContext = {
  isIdle: () => !streaming && !compacting && !otherBusy,
  sessionManager: {
    getSessionId: () => nextSession,
    getSessionFile: () => `${process.env.CREW_PI_SESSION_FILE}.next`,
    getBranch: () => [],
  },
};
await handlers.session_start({}, nextContext);
await waitFor(
  () => sent.length === 2,
  "replacement session did not claim next message",
);
if (!sent[1].message.content.includes(secondId)) {
  throw new Error("wrong next message");
}
await delay(1_800);
if (markerId() !== secondId) {
  throw new Error("old ack callback changed replacement delivery state");
}
if (ackAttempts() !== 1) {
  throw new Error("replacement session retried old acknowledgement");
}
await handlers.session_shutdown();
''')
        self.assertFalse(self.received_path(runtime, second_id).exists())

    def test_old_claim_callback_is_ignored_after_session_switch(self):
        runtime = self.runtime(delay_claim_ms=1_500)
        first_id = runtime["ids"][0]
        self.run_script(runtime, r'''await delay(600);
await handlers.session_shutdown();
const nextSession = "66666666-6666-4666-8666-666666666666";
const nextContext = {
  isIdle: () => !streaming && !compacting && !otherBusy,
  sessionManager: {
    getSessionId: () => nextSession,
    getSessionFile: () => `${process.env.CREW_PI_SESSION_FILE}.next`,
    getBranch: () => [],
  },
};
await handlers.session_start({}, nextContext);
await waitForClaim();
await delay(800);
if (sent.length !== 0) {
  throw new Error("old claim was dispatched in new session");
}
if (ackAttempts() !== 0) {
  throw new Error("old claim was acknowledged in new session");
}
if (markerId() !== JSON.parse(process.env.CREW_MESSAGE_IDS)[0]) {
  throw new Error("old claim lost its durable hold");
}
await handlers.session_shutdown();
''')
        self.assertFalse(self.received_path(runtime, first_id).exists())

    def test_confirmation_requires_matching_in_flight_id(self):
        runtime = self.runtime(count=2)
        self.run_script(runtime, r'''const [firstId, secondId] = JSON.parse(process.env.CREW_MESSAGE_IDS);
otherBusy = true;
await waitForClaim();
await handlers.message_end({ message: {
  role: "custom", customType: "crew-message", details: {},
} });
await handlers.message_end({ message: {
  role: "custom", customType: "crew-message",
} });
if (sent.length !== 0) throw new Error("confirmation cleared a claim before send");
otherBusy = false;
streaming = true;
await handlers.agent_start();
await waitFor(() => sent.length === 1, "busy extension did not steer");
await handlers.message_end({ message: {
  role: "custom", customType: "crew-message", details: { id: "not-the-claim" },
} });
streaming = false;
await handlers.agent_settled();
await waitFor(() => sent.length === 2, "wrong ID cleared the in-flight claim");
if (!sent[1].message.content.includes(firstId)) {
  throw new Error("fallback lost the unconfirmed claim");
}
await completeMessageEnd(1);
execFileSync("crew-nodes", ["ack", firstId]);
streaming = true;
await handlers.agent_start();
await waitFor(() => sent.length === 3, "second busy message was not steered");
if (!sent[2].message.content.includes(secondId)) throw new Error("wrong second message");
await completeMessageEnd(2);
streaming = false;
await handlers.agent_settled();
await delay(800);
if (sent.length !== 3) throw new Error("confirmed steer was resent");
await handlers.session_shutdown();
''')

    def test_unconfirmed_steer_falls_back_to_idle_delivery(self):
        runtime = self.runtime()
        self.run_script(runtime, r'''streaming = true;
await handlers.agent_start();
await waitForClaim();
await waitFor(() => sent.length === 1, "busy extension did not steer");
streaming = false;
await handlers.agent_settled();
await waitFor(() => sent.length === 2, "unconfirmed steer was not retried on idle");
if (sent[1].delivery.triggerTurn !== true || sent[1].delivery.deliverAs) {
  throw new Error("fallback did not use idle delivery");
}
await handlers.session_shutdown();
''')

    def test_sync_send_failure_retries_claim(self):
        runtime = self.runtime(fail_first_send=True)
        self.run_script(runtime, r'''await waitForClaim();
await waitFor(() => sent.length === 1, "send failure did not retry");
if (sent[0].delivery.deliverAs) {
  throw new Error("idle retry unexpectedly used steer delivery");
}
await handlers.session_shutdown();
''')

    def test_out_of_band_ack_drops_held_message_and_claims_next(self):
        runtime = self.runtime(count=2)
        self.run_script(runtime, r'''const [firstId, secondId] = JSON.parse(process.env.CREW_MESSAGE_IDS);
otherBusy = true;
await waitForClaim();
await delay(150);
execFileSync("crew-nodes", ["ack", firstId]);
otherBusy = false;
await waitFor(() => sent.length === 1, "next message was not dispatched");
if (!sent[0].message.content.includes(secondId)) {
  throw new Error("wrong message dispatched");
}
if (sent[0].message.content.includes(firstId)) {
  throw new Error("held acknowledged message was reinjected");
}
await handlers.session_shutdown();
''')

    def test_ack_allows_next_claim_to_progress(self):
        runtime = self.runtime(count=2)
        first_id, second_id = runtime["ids"]
        self.run_script(runtime, r'''const [firstId, secondId] = JSON.parse(process.env.CREW_MESSAGE_IDS);
await waitForClaim();
await waitFor(() => sent.length === 1, "first message was not delivered");
if (!sent[0].message.content.includes(firstId)) throw new Error("wrong first message");
execFileSync("crew-nodes", ["ack", firstId]);
await waitFor(() => sent.length === 2, "next claim did not progress after ack");
if (!sent[1].message.content.includes(secondId)) throw new Error("wrong second message");
await handlers.session_shutdown();
''')
        self.assertTrue((runtime["receiver"] / "received" / f"{first_id}.json").is_file())
        self.assertTrue((runtime["receiver"] / ".delivery.json").is_file())

    def test_compaction_holds_claim_during_active_run_then_steers(self):
        runtime = self.runtime()
        self.run_script(runtime, r'''streaming = true;
await handlers.agent_start();
await handlers.session_before_compact();
await waitForClaim();
await delay(700);
if (sent.length !== 0) throw new Error("active compaction dispatched the claim");
await handlers.session_compact();
await waitFor(() => sent.length === 1, "successful compaction did not release steer");
if (sent[0].delivery.deliverAs !== "steer") {
  throw new Error("active run did not receive a steer after compaction");
}
await handlers.session_shutdown();
''')


if __name__ == "__main__":
    unittest.main()
