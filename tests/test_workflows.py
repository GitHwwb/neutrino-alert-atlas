from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def load_workflow(name: str) -> dict:
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


class WorkflowContractTests(unittest.TestCase):
    def test_scheduled_update_deploys_without_relying_on_push_trigger(self):
        workflow = load_workflow("update-events.yml")

        self.assertIn("schedule", workflow["on"])
        self.assertIn("workflow_dispatch", workflow["on"])
        self.assertNotIn("push", workflow["on"])
        self.assertEqual(workflow["permissions"]["pages"], "write")

        steps = workflow["jobs"]["update-and-deploy"]["steps"]
        checkout = next(
            step for step in steps
            if step.get("uses", "").startswith("actions/checkout@")
        )
        self.assertEqual(checkout["with"]["ref"], "main")
        used_actions = [step["uses"] for step in steps if "uses" in step]
        self.assertTrue(any(action.startswith("actions/deploy-pages@") for action in used_actions))
        self.assertTrue(any(step.get("name") == "Verify deployed catalog" for step in steps))

    def test_human_push_workflow_keeps_pages_deployment(self):
        workflow = load_workflow("pages.yml")

        self.assertIn("push", workflow["on"])
        self.assertEqual(workflow["on"]["push"]["branches"], ["main"])
        self.assertEqual(workflow["permissions"]["pages"], "write")
        checkout = next(
            step for step in workflow["jobs"]["deploy"]["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        )
        self.assertEqual(checkout["with"]["ref"], "main")

    def test_all_external_actions_are_pinned_to_full_commit_sha(self):
        for workflow_name in ("pages.yml", "update-events.yml"):
            workflow = load_workflow(workflow_name)
            for job in workflow["jobs"].values():
                for step in job["steps"]:
                    if "uses" not in step:
                        continue
                    self.assertRegex(
                        step["uses"],
                        re.compile(r"^[^@]+@[0-9a-f]{40}$"),
                        f"{workflow_name}: {step['uses']}",
                    )


if __name__ == "__main__":
    unittest.main()
