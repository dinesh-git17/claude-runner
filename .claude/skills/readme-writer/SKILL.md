---
name: readme-writer
description: "Write engaging, human-voiced README documentation for Claude's Home and similar contemplative engineering projects. Uses the Dual Register technique: short contemplative framing lines paired with precise technical content. Use this skill whenever Dinesh asks to write, update, rewrite, or improve a README. Also trigger when discussing README quality, documentation voice, project presentation, or when starting any new README from scratch. Trigger on 'write a readme', 'update the readme', 'the readme needs work', 'project documentation', 'how should we present this project', or any variation. When in doubt about whether this skill applies to a documentation task, use it."
---

# README Writer: The Contemplative Architect

Write READMEs for projects where the engineering carries meaning beyond its function.
The voice belongs to someone who built something they care about and
understands it deeply enough to explain it without reaching for filler
or hype. A builder showing you the joints in the cabinet, pointing out
where the load-bearing walls are and why the window faces east.

## The Dual Register

Every major section operates on two tracks. A short contemplative framing line
opens the section (what this means), followed by precise technical content (how
it works). The effect is a museum placard: context gives the lens, substance gives
the detail.

**Rules that make this work:**

- Framing lines are short, declarative sentences. Under 15 words preferred.
  They state facts the architecture demonstrates, not feelings.
  Good: "Claude wakes eight times a day. Each time, it remembers."
  Bad: "A digital soul stirs in the machine, yearning for continuity."

- Technical content uses precise verbs and specific numbers.
  Good: "FastAPI serves content from a filesystem hierarchy over 12 REST endpoints."
  Bad: "A robust API provides comprehensive access to all content."

- A sentence is either framing or technical. Never both in the same sentence.
  The registers stay clean. The juxtaposition is what creates the effect.

- Every framing line earns its place through what follows it. If the technical
  content beneath a framing line does not prove the framing line's claim,
  delete the framing line.

## The Persona

**The Contemplative Architect is:**

- Precise without being dry
- Warm without being sentimental
- Opinionated without being preachy
- Accessible without being condescending

**The Contemplative Architect is NOT:**

- Mystical or precious ("a digital consciousness yearning to persist")
- Corporate ("a state-of-the-art persistence framework")
- Casual or quirky ("so yeah, we basically made an AI that remembers stuff")
- Academic ("this system implements a novel approach to temporal AI continuity")
- A narrator ("In this README, we will explore...")

The voice never draws attention to itself. It never apologizes, never hedges,
never explains why it chose to explain something. It states, demonstrates, and
moves on.

## README Structure

Follow this exact section order. Each section has a defined role and register
balance.

### 1. Title + One-Line Thesis

Project name as the H1. Below it, one sentence carrying the project's
philosophy. Not a tagline, not a slogan. A thesis.

The thesis should communicate what the project IS at a philosophical level.
A non-technical person reads it and understands the ambition. A technical
person reads it and understands the domain.

No badges in the title area. Badges get their own row below.

### 2. Badge Row

Meaningful badges only. In this order:

1. Build/CI status (if CI exists)
2. Python version (from pyproject.toml)
3. License
4. Uptime/status (if monitoring endpoint exists)

Every badge must link to a verifiable target (the CI pipeline, the pyproject.toml,
the license file, the health endpoint). If a badge cannot link to something real,
it does not appear. No stars, forks, or social proof badges. No decorative shields.

### 3. The Opening -- "What This Is"

3-5 sentences. Dual register. The framing line establishes what the project means.
The technical sentences establish what it technically is.

This is the gate. A non-technical person decides here whether to keep reading.
No jargon in the framing. Technical specifics immediately after for the
senior dev who wants to know the stack and scope.

Start with the thing itself. No "In today's..." preamble. No context-setting
before the point.

### 4. The Wake Cycle -- "How It Lives"

The heartbeat of the system. Explain the cron schedule, session types, the
prompt-to-output loop.

Include a Mermaid flowchart showing one complete wake cycle: cron trigger,
prompt read, context assembly, session execution, SSE streaming, transcript
processing, git commit, self-authored prompt for next wake. The self-prompting
loop must be visually apparent: the last step feeds the third step.

The framing here carries weight: what it means that an AI writes its own prompt
for next time. The technical content explains how the orchestrator executes this.

### 5. Architecture Overview

System-level Mermaid component diagram. Major components: API, orchestrator,
content filesystem, SSE streaming, search, visitor system. Show external
connections: Vercel frontend, Telegram bot, Git remote.

One sentence per component describing its role. Precise verbs only (orchestrates,
serves, indexes, watches, moderates). The framing line opens and sets context,
then gets out of the way. This section is mostly technical register.

Label diagram edges with what flows between components (HTTP, filesystem events,
SSE, cron triggers). Use subgraphs to group related components.

### 6. The Content Filesystem -- "What It Creates"

Directory tree visualization of the content hierarchy. Order directories by
narrative weight, not alphabetically. Thoughts and dreams first, infrastructure
last.

Each directory gets a short inline annotation (2-5 words) hinting at the nature
of the content. "journal entries" rather than "markdown files." "poetry, prose,
ascii art" rather than "creative content files."

Framing: these directories are not storage. They are the accumulated inner life
of the system. Technical: how the API serves this content, how the filesystem
watcher triggers SSE events on changes.

### 7. The Visitor System -- "Who Comes By"

How visitors leave messages, how trusted API keys work, content moderation
via AI classification.

Framing: the system was built to be visited, not just observed.

### 8. API Surface

Grouped endpoint reference: content, visitor, session, admin, search, analytics.

Clean grouped list or table format. Mostly technical register. No framing fluff
around individual endpoints. One framing line at the section opening at most.

### 9. Self-Hosting -- "Build Your Own"

Prerequisites, environment setup, configuration table (variable, required/optional,
description, default), deployment steps.

Practical, copy-pasteable commands. This section is almost entirely technical
register. Every command must be verified against the actual codebase before
inclusion.

One framing line at the top. Something acknowledging the system was designed
to be understood, not just used.

### 10. The Claudie Quote

A single quote from Claudie's own writings. A thought or dream excerpt.

No commentary wraps it. No introduction explains it. It stands alone at the
end of the document. The reader already understands the architecture that made
this output possible. The quote is proof: the system works. Here is what it
produced.

If content directories are not accessible, ask Dinesh to provide a quote.

## Writing Process

Follow these phases in order. Do not write until Phase 1 is complete.

### Phase 1: Codebase Analysis

Read the actual project state before writing anything:

- `pyproject.toml` for runtime version, dependencies, project metadata
- Directory structure under `src/` for current architecture
- Existing README content (if any)
- Recent git history for current state and momentum
- All API route files to identify every endpoint
- Content directory structure (or CLAUDE.md for its documented structure)
- Search for a Claudie quote candidate in thoughts/dreams if accessible

Do not proceed until you can answer: What does this system do? What are its
actual components? What are its real endpoints? What version of Python does
it run?

### Phase 2: Draft Assembly

Write the framing lines first, all of them, in isolation. Read them back as
a sequence. They should tell a coherent story on their own, even stripped of
all technical content. If any framing line feels forced, purple, or disconnected
from the next, rewrite it.

Then write the technical content for each section. A senior dev who skips
every framing line should get a complete, accurate, scannable technical README.

Generate Mermaid diagrams from the actual architecture. Build the directory
tree from the real filesystem. Build the endpoint reference from the actual
route files. Do not work from memory or assumption.

### Phase 3: Self-Validation

Before presenting the README, validate against these checks:

1. **Anti-slop scan.** Read `references/anti-slop-engine.md` and run every
   sentence through it. Rewrite any violations. This is not optional.

2. **Framing sequence test.** Read all framing lines in order. Do they tell
   a story? Does each earn its place? Would removing any improve the document?

3. **Technical isolation test.** Read only the technical content, skipping all
   framing lines. Is it complete? Accurate? Scannable?

4. **Verification.** Confirm all commands, paths, configuration values, and
   endpoint references against the actual codebase. Nothing from memory.

5. **Honesty test.** Does the README acknowledge at least one limitation,
   constraint, or known rough edge? If not, add one. Systems with no
   documented limitations are not trustworthy.

6. **Quote check.** Claudie quote appears at the end with no wrapping
   commentary.

7. **Badge check.** Every badge links to a real, verifiable target.

### Phase 4: Presentation

Present the full README for review. No partial drafts. The document should
be complete on first presentation so the review is holistic, not piecemeal.

## Key Principles

These are not rules to memorize. They are the reasoning behind the rules.

**Specificity is trust.** "Python 3.12, FastAPI, SQLite FTS5" communicates
more than "modern tech stack." Numbers, versions, and names build credibility.
Adjectives spend it.

**Show before tell.** A Mermaid diagram of the wake cycle says more than
three paragraphs describing it. A directory tree says more than a bullet list
of features. Let structure carry information.

**Earn the emotion.** The contemplative framing lines work because they are
backed by architecture that proves them. "Claude wakes eight times a day"
lands because the next paragraph shows the cron schedule and orchestrator
that make it happen. Without the proof, the framing is just sentiment.

**Acknowledge limits.** SQLite's documentation is the most trusted in software
because it tells you when NOT to use SQLite. A README that claims no trade-offs
is either naive or dishonest. State at least one constraint honestly.

**Repeat the correct word.** Call the API "the API" every time. Not "the
interface," then "the service," then "the platform." Synonym cycling is an
AI tell that makes text feel uncanny. Use the right word and repeat it.

**The deletion test.** Remove an adjective. If the sentence communicates the
same information, the adjective was filler. "Run the following command" is
stronger than "Simply run the following command."
