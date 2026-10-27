"""`git fleetlog ask-agent`: the agent on the setup, or in one repo, here or
on another machine over ssh."""

import os
import subprocess
from pathlib import Path

from fleetlog import agent
from tests.fleet import FleetTest

COMMAND = Path(__file__).resolve().parent.parent / "bin" / "git-fleetlog"
# A folder a shell would trip over, if one ever read it.
ODD = "Projects/it's $(touch pwned) \"a\" `b`"


class AgentTest(FleetTest):
    def ask(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(COMMAND), "ask-agent", *args], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)

    def test_the_setup_agent_gets_the_guide(self):
        done = self.ask()
        self.assertEqual(done.returncode, 0, done.stderr)
        [[_, prompt]] = self.fleet.calls("omarchy-agent-prompt")
        self.assertIn(str(agent.SETUP), prompt)
        self.assertIn(str(COMMAND), prompt)

    def test_the_setup_agent_starts_with_a_config_that_does_not_read(self):
        self.fleet.config("[main\n")
        self.assertEqual(self.ask().returncode, 0)
        self.assertEqual(len(self.fleet.calls("omarchy-agent-prompt")), 1)

    def test_with_no_default_agent_the_picker_opens(self):
        self.fleet.no_agent()
        self.assertEqual(self.ask().returncode, 0)
        self.assertEqual(self.fleet.calls("omarchy-menu"), [agent.PICK[1:]])
        self.assertEqual(len(self.fleet.calls("notify-send")), 1)
        self.assertEqual(self.fleet.calls("omarchy-agent-prompt"), [])

    def test_a_repo_here_starts_the_agent_in_it(self):
        repo = self.fleet.repo("anvil", ODD)
        done = self.ask("--", "anvil", str(repo), "-anvil: 2 commits on main not pushed")
        self.assertEqual(done.returncode, 0, done.stderr)
        [[cwd, prompt]] = self.fleet.calls("omarchy-agent-prompt")
        self.assertEqual(cwd, str(repo))
        self.assertIn("follow this guide", prompt.lower())
        self.assertIn(agent.REPO.read_text(), prompt)
        self.assertIn('"-anvil: 2 commits on main not pushed"', prompt)
        self.assertFalse((repo / "pwned").exists())

    def test_a_repo_elsewhere_starts_that_machines_agent_there(self):
        repo = self.fleet.repo("bench", ODD)
        line = "bench: branch \x1b[31mtry was never pushed (1 commit)"
        done = self.ask("--", "bench", str(repo), line)
        self.assertEqual(done.returncode, 0, done.stderr)
        [launch] = self.fleet.calls("omarchy-launch-tui")
        self.assertEqual(launch[:6], ["--app-id=org.omarchy.agent", "ssh", "-t", "--", "bench",
                                      launch[5]])
        # Nothing from the machine is in the command the far side's shell reads.
        self.assertNotIn("Projects", launch[5])
        self.assertNotIn("never pushed", launch[5])

        self.fleet.clear_calls()
        subprocess.run(launch[1:], stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
                       check=True)
        [[cwd, inline, prompt]] = self.fleet.calls("omarchy-agent-prompt")
        self.assertEqual((cwd, inline), (str(repo), "--inline"))
        self.assertIn("'bench', in an ssh session", prompt)
        self.assertIn('"bench: branch [31mtry was never pushed (1 commit)"', prompt)
        self.assertFalse((self.fleet.home("bench") / "pwned").exists())
        self.assertFalse((repo / "pwned").exists())

    def test_with_no_agent_on_the_far_side_it_leaves_a_shell(self):
        repo = self.fleet.repo("bench", "Projects/tool")
        self.assertEqual(self.ask("--", "bench", str(repo)).returncode, 0)
        [launch] = self.fleet.calls("omarchy-launch-tui")
        self.fleet.no_agent()
        # The shell it leaves is `true` here, so the test does not wait on one.
        done = subprocess.run(launch[1:], stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=30, env={**os.environ, "SHELL": "true"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("no default coding agent", done.stdout)
        self.assertEqual(self.fleet.calls("omarchy-agent-prompt"), [])

    def test_refuses_a_machine_it_does_not_know_or_a_folder_that_is_not_a_path(self):
        done = self.ask("--", "nowhere", "/tmp")
        self.assertEqual(done.returncode, 2)
        self.assertIn("no machine 'nowhere'", done.stderr)
        done = self.ask("--", "anvil", "Projects/tool")
        self.assertEqual(done.returncode, 2)
        self.assertIn("is not a full path", done.stderr)
        done = self.ask("--", "anvil", str(self.fleet.home("anvil") / "gone"))
        self.assertEqual(done.returncode, 2)
        self.assertIn("is not on anvil any more", done.stderr)
        self.assertEqual(self.fleet.calls("omarchy-agent-prompt"), [])
