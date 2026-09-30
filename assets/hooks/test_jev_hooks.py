"""Run: python3 .claude/hooks/test_jev_hooks.py

Plumbing tests for the Jev hooks against a fake Jev server (no key, no network), in a
throwaway project so they don't depend on your repo. They prove each hook reads Claude
Code's input, asks the right questions, acts on the answers, and fails open. They say
nothing about Jev's real accuracy.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ANSWERS = {}  # regex on question text -> probability or choice


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        out = {}
        for key, q in body["questions"].items():
            hit = next((v for rx, v in ANSWERS.items() if re.search(rx, q.get("instructions", ""), re.S)), None)
            if q["type"] == "choice":
                pick = hit if hit in q["criteria"] else "none"
                out[key] = {"type": "choice", "choice": pick, "probabilities": {pick: 0.9}}
            else:
                out[key] = {"type": "boolean", "probability": hit if isinstance(hit, float) else 0.05}
        data = json.dumps({"answers": out}).encode()
        self.send_response(200)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# Throwaway project: one skill, one edit rule, one spec with one tested and one untested rule.
ROOT = tempfile.mkdtemp(prefix="jev-hooks-")
for path, text in {
    ".claude/skills/review-ui/SKILL.md": "---\nname: review-ui\ndescription: Review UI changes.\n---\n",
    ".claude/skills/deploy/SKILL.md": "---\nname: deploy\ndescription: >-\n  Ship to prod.\n  Use for releases.\nmodel: x\n---\nbody --- text\n",
    ".claude/jev-rules.json": json.dumps({"rules": [{"id": "no-db-frontend", "on": "edit", "paths": "^web/",
                                                      "rule": "Frontend code never talks to the database directly.", "source": "CLAUDE.md"}]}),
    ".claude/jev-spec.json": json.dumps({"specs": [{"spec": "docs/SPEC.md", "watch": "^api/"}]}),
    "docs/SPEC.md": "# Access\n\n- Guests cannot open the admin page.\n- Users can only see their own orders.\n",
    "tests/test_access.py": "def test_guest_admin():\n    assert get('/admin', as_='guest').status == 403\n",
}.items():
    Path(ROOT, path).parent.mkdir(parents=True, exist_ok=True)
    Path(ROOT, path).write_text(text)

server = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=server.serve_forever, daemon=True).start()
RUN = f"test{os.getpid()}-"  # fresh per-session state every run
ENV = {**os.environ, "AI_GATEWAY_API_KEY": "test", "CLAUDE_PROJECT_DIR": ROOT,
       "JEV_URL": f"http://127.0.0.1:{server.server_port}/v1/evaluate"}


def hook(name, payload, env=ENV):
    r = subprocess.run([sys.executable, os.path.join(HERE, name)], input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr


def edit(path, new, session="t"):
    return {"session_id": RUN + session, "tool_name": "Edit",
            "tool_input": {"file_path": os.path.join(ROOT, path), "old_string": "x", "new_string": new}}


# Skill roster: plain and YAML block-scalar descriptions both parse.
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("skill_pick", os.path.join(HERE, "jev-skill-pick.py"))
skill_pick = importlib.util.module_from_spec(spec); spec.loader.exec_module(skill_pick)
assert skill_pick.skills(ROOT) == {"deploy": "Ship to prod. Use for releases.", "review-ui": "Review UI changes."}

# Skill pick: confident pick adds context, "none" adds nothing.
ANSWERS.clear(); ANSWERS["Which skill"] = "review-ui"
_, out, _ = hook("jev-skill-pick.py", {"prompt": "restyle the settings page"})
assert "review-ui" in json.loads(out)["hookSpecificOutput"]["additionalContext"]
ANSWERS.clear()
assert hook("jev-skill-pick.py", {"prompt": "what does this function do?"})[1] == ""

# Rule enforcer: breaking edit denied, harmless edit allowed, unrelated path never asks.
ANSWERS.clear(); ANSWERS["talks to the database"] = 0.96
_, out, _ = hook("jev-rules.py", edit("web/x.tsx", "db.query('select * from users')", "s1"))
assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
ANSWERS.clear()
assert hook("jev-rules.py", edit("web/x.tsx", "const a = 1", "s2"))[1] == ""
assert hook("jev-rules.py", edit("docs/SPEC.md", "anything", "s3"))[1] == ""

# Loop guard: third block on the same file becomes a note, not a deny.
ANSWERS["talks to the database"] = 0.96
for _ in range(2):
    hook("jev-rules.py", edit("web/y.tsx", "db.query(1)", "s4"))
_, out, _ = hook("jev-rules.py", edit("web/y.tsx", "db.query(1)", "s4"))
assert "permissionDecision" not in out and "already blocked twice" in out

# Fail open: Jev down or no key -> nothing blocks.
down = {**ENV, "JEV_URL": "http://127.0.0.1:9/v1/evaluate"}
assert hook("jev-rules.py", edit("web/z.tsx", "db.query(1)", "s5"), down)[1] == ""
assert hook("jev-skill-pick.py", {"prompt": "restyle the settings page"}, {**ENV, "AI_GATEWAY_API_KEY": ""})[1] == ""

# Spec hook: edit to watched code with an untested rule -> exit 2 naming only that rule; once per session.
ANSWERS.clear(); ANSWERS["Guests cannot open the admin page"] = 0.95
code, _, err = hook("jev-spec-hook.py", edit("api/orders.py", "x", "p1"))
assert code == 2 and "1 of 2 rules have no test" in err and "own orders" in err, err
assert hook("jev-spec-hook.py", edit("api/orders.py", "x", "p1"))[0] == 0
assert hook("jev-spec-hook.py", edit("web/page.tsx", "x", "p2"))[0] == 0  # not watched

print("ok: jev hooks plumbing")
