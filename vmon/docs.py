"""Documentation links built from the URL templates in flows.toml [docs]."""
from urllib.parse import quote_plus


class DocLinks:
    def __init__(self, data):
        docs = data.get("docs", {})
        self.tcl = docs.get("tcl_command", "")
        self.message = docs.get("message_search", "")
        self.steps = docs.get("steps", {})
        self.reports = docs.get("reports", {})
        self.commands = set(self.reports.values())

    def _expand(self, value):
        if not value:
            return None
        return value if "://" in value else (self.tcl.format(command=value) if self.tcl else None)

    def step(self, step_id):
        return self._expand(self.steps.get(step_id))

    def report(self, kind):
        return self._expand(self.reports.get(kind))

    def command(self, name):
        """UG835 page for a command that is a known report command (child command nodes)."""
        return self._expand(name) if name in self.commands else None

    def message_url(self, msg_id):
        if not self.message or not msg_id:
            return None
        return self.message.replace("{query}", quote_plus(msg_id))

    def annotate(self, stages):
        """Set Node.doc_url on every node: steps from [docs.steps], children inherit unless they are a report command."""
        def walk(node, url):
            first = node.label.split(" ", 1)[0] if node.label else ""
            node.doc_url = self.command(first) or url
            for child in node.children:
                walk(child, node.doc_url)

        for stage in stages:
            step_id = "synth_design" if stage.id == "synth" else stage.id.rsplit("/", 1)[-1]
            url = self.step(step_id)
            stage.doc_url = url
            for child in stage.children:
                walk(child, url)
