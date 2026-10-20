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
                "PATH": (
                    str(tools) + os.pathsep + str(ROOT / "bin")
                    + os.pathsep + os.environ["PATH"]
                ),
            })
            script = r'''import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
const { default: extension } = await import(
  pathToFileURL(process.env.CREW_EXTENSION_PATH).href
);
const handlers = {};
const sent = [];
let compacting = true;
let streaming = false;
const pi = {
  on: (event, handler) => { handlers[event] = handler; },
  sendMessage: (message, delivery) => { sent.push({ message, delivery }); },
};
extension(pi);
const context = { isIdle: () => !streaming && !compacting };
const delay = (milliseconds) => new Promise((resolve) =>
  setTimeout(resolve, milliseconds));
await handlers.session_start({}, context);
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
for (let attempt = 0; attempt < 40 && sent.length === 0; attempt++) {
  await delay(125);
}
if (sent.length !== 1) throw new Error("idle extension did not dispatch its claim");
if (sent[0].delivery.triggerTurn !== true || sent[0].delivery.deliverAs) {
  throw new Error("idle delivery did not trigger a turn conservatively");
}
if (!sent[0].message.content.includes(process.env.CREW_EXPECTED_MESSAGE_ID)) {
  throw new Error("dispatched message lost its acknowledgement ID");
}
await handlers.session_shutdown();
console.log("PASS Pi compaction claim remains held until idle");
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
            self.assertIn("PASS Pi compaction claim remains held until idle", result.stdout)
            self.assertTrue((receiver / "pending" / f"{message_id}.json").is_file())
            self.assertTrue((receiver / ".delivery.json").is_file())


if __name__ == "__main__":
    unittest.main()
