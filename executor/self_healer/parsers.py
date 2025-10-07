from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional
import xml.etree.ElementTree as ET
import re


@dataclass
class Failure:
    file: str
    line: Optional[int]
    classname: str
    testname: str
    message: str
    traceback: str


@dataclass
class TestSummary:
    failures: List[Failure]
    errors: List[Failure]
    tests: int
    failures_count: int
    errors_count: int
    skipped: int


def parse_junit(xml_path: Path) -> TestSummary:
    """Parse pytest JUnit XML output into a structured summary."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    failures, errors = [], []
    total = 0
    skipped = 0

    for ts in root.iter("testsuite"):
        total += int(ts.attrib.get("tests", 0))
        skipped += int(ts.attrib.get("skipped", 0))
        for tc in ts.iter("testcase"):
            classname = tc.attrib.get("classname", "")
            name = tc.attrib.get("name", "")
            file_attr = tc.attrib.get("file") or ""
            line_attr = tc.attrib.get("line")
            line_int = int(line_attr) if line_attr and line_attr.isdigit() else None

            def collect(tag: str):
                node = tc.find(tag)
                if node is None:
                    return None
                msg = node.attrib.get("message", "")
                tb = (node.text or "").strip()
                return Failure(file_attr, line_int, classname, name, msg, tb)

            if (f := collect("failure")):
                failures.append(f)
            if (e := collect("error")):
                errors.append(e)

    return TestSummary(
        failures=failures,
        errors=errors,
        tests=total,
        failures_count=len(failures),
        errors_count=len(errors),
        skipped=skipped,
    )


PATCH_BLOCK_RE = re.compile(
    r"```patch:(?P<path>[^\n`]+)\n(?P<body>.*?)```",
    re.DOTALL | re.IGNORECASE,
)


@dataclass
class Patch:
    path: str
    content: str
    summary: str = ""


def parse_patches(text: str) -> List[Patch]:
    """Extract fenced code blocks representing full file patches."""
    patches: List[Patch] = []
    for m in PATCH_BLOCK_RE.finditer(text):
        patches.append(Patch(m.group("path").strip(), m.group("body")))
    return patches