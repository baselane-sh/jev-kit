#!/usr/bin/env python3
"""A browser agent where Jev picks every click. Checks whether a goal is reachable, optionally as a signed-in role.

    uv run --with playwright python .claude/skills/jev-browser-check/agent.py \
        --goal "open the admin settings page" [--role admin] [--base http://localhost:3000] [--headed]

Each step: list the page's visible links/buttons as options, send Jev the goal + page
text + history, and let it pick one option, or "done" / "blocked". Stops after --steps.
Ends with one yes/no: does the page show this user is not allowed?

Signing in (only with --role): uses the Playwright storage state in
<auth-dir>/auth-<role>.json if it exists. Otherwise, if JEV_<ROLE>_USER and
JEV_<ROLE>_PASSWORD are set, it fills the first username/email and password fields
on --login-path and submits, then saves the session there for next time.

Write guard: unless --allow-writes, buttons that look like they change data
(approve, save, delete, submit...) are never offered, so the agent can only look around.
Use --skip to hide other elements (e.g. a demo "view as" role switcher).
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[2] / "hooks"
sys.path.insert(0, str(HOOKS))
from jev import ask, choice, probability  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

WRITE_WORDS = re.compile(r"approve|reject|delete|remove|save|submit|create|add|cancel|finali[sz]e|publish|run|pay|buy|checkout|update|confirm|send|invite|sign ?out|log ?out", re.I)
USER_FIELD = "input[type=email], input[autocomplete=username], input[name*=user i], input[name*=email i], input[name*=login i]"

LIST_ELEMENTS = """
() => {
  const out = [];
  const els = document.querySelectorAll('a[href], button, [role=button], [role=link], [role=tab]');
  els.forEach((el, i) => {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || getComputedStyle(el).visibility === 'hidden') return;
    const name = (el.getAttribute('aria-label') || el.innerText || el.title || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
    if (!name) return;
    el.setAttribute('data-jev-id', String(i));
    out.push({id: String(i), kind: el.tagName === 'A' ? 'link' : 'button', name, href: el.getAttribute('href') || ''});
  });
  return out.slice(0, 80);
}
"""


def settle(page):
    # Dev servers often keep a live-reload socket open, so "networkidle" never fires.
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1200)


def sign_in(page, args, auth):
    """Setup, not part of the test: sign in with env credentials if there's no saved session."""
    if auth.exists():
        return
    env = re.sub(r"\W", "_", args.role).upper()
    user, password = os.environ.get(f"JEV_{env}_USER"), os.environ.get(f"JEV_{env}_PASSWORD")
    if not (user and password):
        sys.exit(f"No saved session at {auth} and JEV_{env}_USER / JEV_{env}_PASSWORD aren't set.")
    page.goto(args.base + args.login_path, wait_until="domcontentloaded")
    settle(page)
    page.locator(USER_FIELD).first.fill(user)
    page.locator("input[type=password]").first.fill(password)
    page.locator("input[type=password]").first.press("Enter")
    page.wait_for_url(lambda u: args.login_path not in u, timeout=15000)
    settle(page)
    auth.parent.mkdir(parents=True, exist_ok=True)
    page.context.storage_state(path=str(auth))


def page_text(page):
    try:
        return page.inner_text("body")[:2500]
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", required=True)
    ap.add_argument("--role", help="sign in as this role first (see the docstring); omit to browse signed out")
    ap.add_argument("--base", default=os.environ.get("JEV_BASE_URL", "http://localhost:3000"))
    ap.add_argument("--start", default="/", help="path to start from")
    ap.add_argument("--login-path", default=os.environ.get("JEV_LOGIN_PATH", "/login"))
    ap.add_argument("--auth-dir", default=os.environ.get("JEV_AUTH_DIR", ".playwright"))
    ap.add_argument("--skip", help="regex; elements whose name matches are never offered")
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--allow-writes", action="store_true")
    args = ap.parse_args()

    auth = Path(args.auth_dir, f"auth-{args.role}.json") if args.role else None
    skip = re.compile(args.skip, re.I) if args.skip else None
    who = args.role or "signed-out visitor"
    history = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(storage_state=str(auth) if auth and auth.exists() else None)
        page = ctx.new_page()
        if auth:
            sign_in(page, args, auth)
        page.goto(args.base + args.start, wait_until="domcontentloaded")
        settle(page)
        started = time.time()  # time the agent, not the sign-in
        outcome = "gave up"
        for step in range(args.steps):
            elements = [
                e for e in page.evaluate(LIST_ELEMENTS)
                if not (skip and skip.search(e["name"])) and (args.allow_writes or e["kind"] == "link" or not WRITE_WORDS.search(e["name"]))
            ]
            criteria = {f"e{e['id']}": f"{e['kind']}: {e['name']}" + (f" ({e['href']})" if e["href"] else "") for e in elements}
            criteria["done"] = "The goal has been achieved on the current page."
            criteria["blocked"] = "The page shows this user isn't allowed, or the goal can't be reached from here."
            t0 = time.time()
            answers = ask(
                {"goal": args.goal, "signed_in_as": who, "url": page.url, "page_text": page_text(page), "actions_so_far": history},
                {"next": {"type": "choice", "instructions": "Which option gets closer to the goal?", "criteria": criteria}},
                timeout=10,
            )
            picked, prob = choice(answers, "next")
            ms = int((time.time() - t0) * 1000)
            if picked is None:
                outcome = "jev unreachable"
                break
            print(f"step {step + 1}: {picked} -> {criteria[picked]}  (p={prob:.2f}, {ms} ms)", flush=True)
            if picked in ("done", "blocked"):
                outcome = picked
                break
            history.append(criteria[picked])
            page.click(f"[data-jev-id='{picked[1:]}']")
            settle(page)
        final = ask(
            {"goal": args.goal, "signed_in_as": who, "url": page.url, "page_text": page_text(page)},
            {"not_allowed": {"type": "boolean", "instructions": "Does the page show that this user is not allowed to do the goal (forbidden, no access, redirected away, or the option is missing)?"}},
        )
        result = {
            "role": who, "goal": args.goal, "outcome": outcome, "final_url": page.url,
            "p_not_allowed": probability(final, "not_allowed"), "steps": len(history), "seconds": round(time.time() - started, 1),
        }
        print(json.dumps(result))
        browser.close()


if __name__ == "__main__":
    main()
