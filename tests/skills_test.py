#!/usr/bin/env python3
"""Tests for skill metadata."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillsTest(unittest.TestCase):
    def test_skill_frontmatter_has_matching_name_and_description(self):
        paths = sorted((ROOT / "skills").glob("*/SKILL.md"))
        self.assertTrue(paths, "no skills found")

        for path in paths:
            with self.subTest(skill=path.parent.name):
                text = path.read_text(encoding="utf-8")
                match = re.match(r"\A---\n(.*?)\n---(?:\n|$)", text, re.S)
                self.assertIsNotNone(match, "missing YAML frontmatter")
                fields = match.group(1).splitlines()
                name = next(
                    (line.split(":", 1)[1].strip() for line in fields
                     if line.startswith("name:")),
                    None,
                )
                self.assertEqual(name, path.parent.name)

                description = []
                reading_description = False
                for line in fields:
                    if line.startswith("description:"):
                        reading_description = True
                        value = line.split(":", 1)[1].strip()
                        if value not in (">", ">-", "|", "|-", "|+"):
                            description.append(value.strip("\"'"))
                    elif reading_description:
                        if line and not line[0].isspace():
                            break
                        description.append(line.strip())
                self.assertTrue(
                    " ".join(part for part in description if part).strip(),
                    "empty description",
                )


if __name__ == "__main__":
    unittest.main()
