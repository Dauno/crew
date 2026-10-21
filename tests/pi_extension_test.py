"""No-inference lifecycle regression for the Pi mailbox extension."""

import importlib.util
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


@unittest.skipUnless(shutil.which("node"), "node is required for extension tests")
class PiExtensionLifecycleTest(unittest.TestCase):
    def test_compaction_claim_waits_for_idle_before_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "crew"
            sender = mailbox.initialize_session(
                SENDER, cli="pi", home=home,
            )
            receiver = mailbox.initialize_session(
                RECIPIENT, cli="pi", home=home,
            )
            tools = Path(temporary) / "tools"
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
                message_id = mailbox.publish_message(
                    RECIPIENT, "only deliver once idle", home=home,
                )
                confirmed_message_id = mailbox.publish_message(
                    RECIPIENT, "confirm while busy", home=home,
                )

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
                "CREW_EXPECTED_MESSAGE_ID": message_id,
                "CREW_CONFIRMED_MESSAGE_ID": confirmed_message_id,
                "PATH": (
                    str(tools) + os.pathsep + str(ROOT / "bin")
                    + os.pathsep + os.environ["PATH"]
                ),
            })
            script = r'''import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { execFileSync } from "node:child_process";
const { default: extension } = await import(
  pathToFileURL(process.env.CREW_EXTENSION_PATH).href
);
const handlers = {};
const sent = [];
let failNextSend = true;
let compacting = true;
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
await handlers.session_start({}, context);
await handlers.session_before_compact();
let marker;
for (let attempt = 0; attempt < 40; attempt++) {
  try {
    marker = JSON.parse(readFileSync(
      `${process.env.CREW_INBOX}/.delivery.json`, "utf8"
    ));
    break;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
    await delay(250);
  }
}
if (!marker) throw new Error("extension did not claim the pending message");
if (sent.length !== 0) throw new Error("compaction delivered a claimed message");
if (marker.id !== process.env.CREW_EXPECTED_MESSAGE_ID) {
  throw new Error("the claimed delivery marker was not retained");
}
await delay(750);
if (sent.length !== 0) throw new Error("compaction delivered a claimed message");
compacting = false;
otherBusy = true;
await handlers.session_compact_failed();
await delay(650);
if (sent.length !== 0) throw new Error("busy non-run state dispatched a message");
otherBusy = false;
streaming = true;
await handlers.agent_start();
for (let attempt = 0; attempt < 40 && sent.length === 0; attempt++) {
  await delay(125);
}
if (sent.length !== 1 || sent[0].delivery.deliverAs !== "steer" ||
    sent[0].delivery.triggerTurn !== true) {
  throw new Error("busy extension did not steer its claimed message");
}
await delay(900);
if (sent.length !== 1) throw new Error("busy extension duplicated a queued steer");
await handlers.message_end({ message: {
  role: "custom", customType: "crew-message", details: { id: "not-the-claim" },
} });
if (!sent[0].message.content.includes(process.env.CREW_EXPECTED_MESSAGE_ID)) {
  throw new Error("dispatched message lost its acknowledgement ID");
}

// An aborted, unconsumed steer is retried on idle.
streaming = false;
await handlers.agent_settled();
for (let attempt = 0; attempt < 20 && sent.length < 2; attempt++) await delay(125);
if (sent.length !== 2 || sent[1].delivery.triggerTurn !== true ||
    sent[1].delivery.deliverAs) {
  throw new Error("unconsumed steer was not retried on idle");
}
const claimed = sent[1].message;
await handlers.message_end({ message: {
  role: "custom", customType: "crew-message", details: claimed.details,
} });
execFileSync("crew-nodes", ["ack", process.env.CREW_EXPECTED_MESSAGE_ID]);
streaming = true;
await handlers.agent_start();
for (let attempt = 0; attempt < 40 && sent.length < 3; attempt++) await delay(125);
if (sent.length !== 3 || sent[2].delivery.deliverAs !== "steer") {
  throw new Error("second busy message was not steered");
}
await handlers.message_end({ message: {
  role: "custom", customType: "crew-message",
  details: { id: process.env.CREW_CONFIRMED_MESSAGE_ID },
} });
streaming = false;
await handlers.agent_settled();
await delay(800);
if (sent.length !== 3) throw new Error("confirmed steer was resent");
await handlers.session_shutdown();
console.log("PASS Pi compaction, steer confirmation, and idle fallback");
'''
            result = subprocess.run(
                [shutil.which("node"), "--experimental-strip-types",
                 "--input-type=module", "-e", script],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PASS Pi compaction, steer confirmation, and idle fallback", result.stdout)
            self.assertTrue((receiver / "received" / f"{message_id}.json").is_file())
            self.assertTrue((receiver / ".delivery.json").is_file())


if __name__ == "__main__":
    unittest.main()
