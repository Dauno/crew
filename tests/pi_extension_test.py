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

JS_SETUP = r'''import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { execFileSync } from "node:child_process";
const { default: extension } = await import(
  pathToFileURL(process.env.CREW_EXTENSION_PATH).href
);
const handlers = {};
const sent = [];
let failNextSend = process.env.CREW_FAIL_FIRST_SEND === "1";
let compacting = false;
let streaming = false;
let otherBusy = false;
const pi = {
  on: (event, handler) => { handlers[event] = handler; },
  sendMessage: (message, delivery) => {
    if (failNextSend) {
      failNextSend = false;
      throw new Error("simulated send failure");
    }
    sent.push({ message, delivery });
  },
};
extension(pi);
const context = { isIdle: () => !streaming && !compacting && !otherBusy };
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
await handlers.session_start({}, context);
'''


@unittest.skipUnless(shutil.which("node"), "node is required for extension tests")
class PiExtensionLifecycleTest(unittest.TestCase):
    def runtime(self, count=1, fail_first_send=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        home = base / "crew"
        sender = mailbox.initialize_session(SENDER, cli="pi", home=home)
        receiver = mailbox.initialize_session(RECIPIENT, cli="pi", home=home)
        tools = base / "tools"
        tools.mkdir()
        crew_nodes = tools / "crew-nodes"
        crew_nodes.write_text(
            f"#!{sys.executable}\n"
            "import subprocess, sys\n"
            f"raise SystemExit(subprocess.run(['bash', "
            f"{str(ROOT / 'bin/crew-nodes')!r}, *sys.argv[1:]], "
            "check=False).returncode)\n"
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
            "CREW_FAIL_FIRST_SEND": "1" if fail_first_send else "0",
            "PATH": (
                str(tools) + os.pathsep + str(ROOT / "bin")
                + os.pathsep + os.environ["PATH"]
            ),
        })
        return {"temporary": temporary, "env": env, "ids": ids,
                "receiver": receiver}

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
await handlers.message_end({ message: {
  role: "custom", customType: "crew-message", details: sent[1].message.details,
} });
execFileSync("crew-nodes", ["ack", firstId]);
streaming = true;
await handlers.agent_start();
await waitFor(() => sent.length === 3, "second busy message was not steered");
if (!sent[2].message.content.includes(secondId)) throw new Error("wrong second message");
await handlers.message_end({ message: {
  role: "custom", customType: "crew-message", details: sent[2].message.details,
} });
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
