"""Small persisted summary of earlier attempts per firmware: ~/.cache/vmon/attempts/<fw_id>.json.

Schema: {"runs": {run_id: {"sig": {...}, "launches": int, "last": {step: [attempt]},
                           "archive": {step: [attempt]}, "sessions": [session]}}}
"""
import json
import os
from pathlib import Path


def default_dir():
    return Path.home() / ".cache" / "vmon" / "attempts"


class AttemptStore:
    def __init__(self, directory, fw_id):
        self.path = Path(directory or default_dir()) / (fw_id + ".json")
        self.data = None
        self._saved = None

    def load(self):
        if self.data is None:
            try:
                self.data = json.loads(self.path.read_text())
                if not isinstance(self.data.get("runs"), dict):
                    raise ValueError
            except (OSError, ValueError, AttributeError):
                self.data = {"runs": {}}
            self._saved = json.dumps(self.data, sort_keys=True)
        return self.data

    def run(self, run_id):
        runs = self.load()["runs"]
        return runs.setdefault(run_id, {"sig": None, "launches": 0, "last": {}, "archive": {}, "sessions": []})

    def save(self):
        """Write only when something changed; failures (read-only home, ...) are ignored."""
        if self.data is None:
            return
        text = json.dumps(self.data, sort_keys=True)
        if text == self._saved:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(text)
            os.replace(tmp, self.path)
            self._saved = text
        except OSError:
            pass
