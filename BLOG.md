# I gave Claude Code a judge. Here's what changed.

Claude Code is good at doing what you ask. It's less good at knowing when to
stop, what to trust, and which of your own rules it's about to break. Most of
that gets handled by CLAUDE.md files that grow forever, by hoping the model
reads them at the right moment, and by you catching the rest in review.

I wanted something that actually checks, in the loop, before the damage is
done. Not another static rule file. A second opinion that runs on every
prompt, every edit, and every commit, and costs close to nothing because it's
answering yes/no questions, not writing code.

That second opinion is a small decision model called Jev, served through
Vercel's AI Gateway. You send it a short description of a situation and a set
of typed questions, it returns probabilities. "Is this risky" comes back as
`{risky: true, probability: 0.87}` instead of a paragraph you have to parse.
Cheap, fast, and precise enough to gate a tool call on.

I built seven hooks and skills around it. Here's what each one does, and why
it earned a place in my `.claude/` folder.

## 1. A rule enforcer that actually reads the diff

Every project accumulates a list of "never do X" rules. They live in
CLAUDE.md, in a Slack thread, in someone's head. Claude reads CLAUDE.md once
per session if you're lucky, and by message forty it's forgotten rule twelve.

I moved my hard rules into a JSON file and wrote a `PreToolUse` hook. Before
every Edit, Write or Bash call, it sends the relevant rules and the proposed
change to Jev as a batch of yes/no questions. If the probability that a rule
is broken crosses a threshold, the tool call gets denied and Claude sees
exactly why. Below that threshold it's a warning, not a block, because a rule
checker that cries wolf gets ignored. A rule can only block the same file
twice per session, then it just warns, so a bad rule can't loop Claude
forever.

The best part: I didn't add a single sentence to CLAUDE.md. The rules live
where they can be checked mechanically instead of hoped for.

## 2. A judge for whether tests actually cover the spec

I write access-control specs and API contracts as markdown docs, and I trust
myself to remember to write tests for them approximately never. So I pointed
a hook at those docs. It watches the code paths that implement each spec, and
after an edit, it asks Jev to compare the spec's rules against what the tests
actually cover. If something is under-tested, Claude gets told in plain
language, once per session per spec, not on every keystroke.

This isn't a coverage percentage. It's closer to a reviewer who read the spec
and the tests and is telling you which sentence in the spec has nothing
backing it up.

## 3. A skill picker that reads the room

I have a handful of project-specific skills. Some sessions need one of them,
most don't. I got tired of either forcing Claude to guess or writing "use the
deploy skill when I say deploy" logic that breaks the moment I phrase it
differently.

Now a `UserPromptSubmit` hook reads the name and description of every skill I
have, hands them to Jev alongside my prompt, and asks which one fits, if any.
When it's confident, it tells Claude to go read that skill file. When it's
not, or the answer is "none", it says nothing. Slash commands are ignored
entirely, since those are already an explicit choice.

## 4. Exploration that skips the parts you don't need

Grep is a blunt instrument on a big repo. Semantic search over an entire
codebase is expensive and slow. What I actually want is somewhere in between:
narrow the field with a keyword pass, then let something smarter than grep
rank what's left by whether it's actually relevant to the task.

That's what this skill does. Keyword filter first, because it's free, then
Jev scores the survivors against the actual question being asked. It doesn't
replace Claude's own judgment, it just means Claude isn't wading through
forty files that happen to contain a matching string.

## 5. A pre-review pass that's honest about what it can't catch

Full code review is expensive to run on every change, so most of us run it
sparingly or not at all until PR time. I wanted a cheap first pass that flags
the changes actually worth slowing down for: did this touch auth, money, a
schema, state that could cause data loss, an API contract, or secrets.

Seven yes/no questions per change, answered in one batch call. If any of them
come back hot, the change gets routed into a proper adversarial review: one
agent plays a reviewer who assumes the code is wrong and has to be convinced
otherwise, another plays the person defending or fixing it, and they go back
and forth until the reviewer is satisfied or gives up with a documented
reason. Most changes never reach that stage. The ones that do get real
scrutiny instead of a rubber stamp.

## 6. Browser QA that clicks the way a human would

Playwright scripts are great once you know exactly what to click. They're
brittle the moment a button moves or gets renamed. I wanted something that
could look at a page the way I do: find the "submit" button by what it says
and where it is, not by a selector that breaks on the next redesign.

This skill pairs Playwright with Jev as a click-picker. Given the page's
visible text, its clickable elements by label, and a goal, it picks the right
element the way a human would, by what it says, and the automation clicks it. It's not a full self-driving test suite. It's the
difference between a script that dies on a CSS class change and one that
survives it.

## 7. Compaction that doesn't quietly rewrite your session

Long sessions eventually hit a context limit and get compacted. The default
behavior summarizes, and summaries lose things: the exact error message from
three tool calls ago, the specific reason you rejected an approach, the file
path you haven't mentioned since. I've had Claude re-suggest something I
already vetoed because the veto didn't survive compaction.

This plugin replaces the default `/compact` with something that keeps
decisions and constraints verbatim instead of paraphrasing them, and uses Jev
to decide what's safe to compress versus what has to stay exact. It also
kicks in on its own once the context is 60% full, well before the hard limit,
so compaction happens early and in smaller steps instead of as one cliff-edge
event at the end.

## Why probabilities instead of another prompt

Every one of these could be "add more to CLAUDE.md and hope." I tried that
for a while. The problem isn't that Claude can't follow instructions, it's
that a growing wall of prose competes for attention with the actual task, and
nothing enforces it. A hook that returns a probability and a reason is
cheaper to run, cheaper to reason about, and it fails open: if the API key is
missing, the request times out, or the Gateway has a bad day, every one of
these hooks does nothing and Claude works exactly like it did before. None of
this can block you. It can only catch things you'd want caught.

## Try it

I packaged all seven as a drop-in `.claude/` folder with a bash installer,
open source under Baselane:

```bash
git clone https://github.com/baselane-sh/jev-kit.git /tmp/jev-kit
cd /path/to/your/project
bash /tmp/jev-kit/install.sh
```

It backs up your settings, wires up the hooks, and asks for a Vercel AI
Gateway key, which you can skip since everything fails open without one.
Uninstalling is one command and only removes what it added.

Repo: [github.com/baselane-sh/jev-kit](https://github.com/baselane-sh/jev-kit)
