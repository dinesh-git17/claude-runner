# Anti-Slop Engine

Read this file during Phase 3 (Self-Validation). Every sentence in the README
must pass these checks. A single violation means rewriting the sentence, not
explaining why it is acceptable.

## Tier 1: Banned Words

These words are always a tell. Replace on sight. No exceptions, no context
where they become acceptable.

delve, tapestry, landscape (metaphorical), realm, paradigm, beacon, testament,
robust, comprehensive, cutting-edge, leverage (as verb meaning "use"), pivotal,
seamless, game-changer, utilize, watershed, vibrant, thriving, showcasing,
bustling, intricate, holistic, actionable, impactful, synergy, interplay,
unleash, unlock, elevate, streamline, empower, foster, harness, revolutionize,
groundbreaking, transformative, cornerstone, paramount, embark, plethora,
myriad, kaleidoscope, symphony, treasure trove, nestled, endeavor, keen,
ascertain, commence, boasts

## Tier 2: Banned Phrases

These phrases are structural tells. Their presence signals AI-generated text
regardless of how good the surrounding content is.

**Opening preambles:**

- "In today's [anything]..."
- "In a world where..."
- "In an era of..."
- "Whether you're [X] or [Y]..."
- "Have you ever wondered..."

**Hedging filler:**

- "It's important to note that..."
- "It's worth mentioning that..."
- "It should be noted that..."
- "As you may know..."
- "Generally speaking..."

**Chatbot artifacts:**

- "Let's dive in"
- "Let's explore"
- "Here's what you need to know"
- "Don't hesitate to..."
- "Feel free to..."
- "I hope this helps"
- "Let me know if you need anything else"

**Significance inflation:**

- "...marking a pivotal moment"
- "...a testament to [something]"
- "...underscores the importance of"
- "...reflecting broader trends"

**The AI negation pattern (most recognizable AI sentence structure):**

- "Not just X -- it's Y"
- "It's not a [thing] -- it's a [grander thing]"
- "More than just a [thing]"

**Participial tail filler (sentences ending with):**

- "...highlighting the importance of..."
- "...underscoring the need for..."
- "...ensuring a seamless experience"
- "...demonstrating the potential for..."
- "...showcasing the commitment to..."

## Tier 3: Structural Patterns

These are patterns that make text feel AI-generated even when individual
words are fine.

**Uniform paragraph length.** If all paragraphs are 3-5 sentences, vary them
deliberately. Some paragraphs should be one sentence. Some should be six.
The length should match the complexity of the point, not a template.

**Synonym cycling.** Call the same thing the same word every time. The API
is "the API." Not "the interface" in paragraph two, "the service" in paragraph
three, "the platform" in paragraph four. Humans repeat the correct word.
AI rotates synonyms to avoid repetition, producing uncanny text.

**The Rule of Three.** AI defaults to listing exactly three items even when
two or four would be more natural. If you catch yourself listing three things,
check whether the count is genuine or reflexive.

**"Is" + adjective.** Sentences where the main verb is a form of "to be"
followed by an adjective ("is powerful", "is flexible", "is fast") must be
rewritten. Replace with a specific verb describing what the thing does.
"The search engine is fast" becomes "The search engine returns results in
under 50ms using FTS5 with BM25 ranking."

**Bolded inline headers on every bullet.** The pattern of **Bold header:**
followed by description on every single bullet point is a strong AI formatting
tell. Use this pattern sparingly or not at all. A bullet point can just be
a sentence.

**Em dash overuse.** AI uses em dashes constantly where commas, colons, or
parentheses would be more natural. Hard limit: one em dash per 1,000 words
maximum in the final README.

**Title case in all headings.** Use sentence case for section headings.
"How it lives" not "How It Lives." Title case on every heading is a
formatting tell.

**Formulaic section openings.** Every section starting with context-setting
before the actual content. Lead with the point when possible.

**The clean ending.** Every section concluding with a summary restating its
significance. Trust the reader. Leave loose threads when they exist.

## Tier 4: Epistemic Rules

These rules address how the README handles certainty and limitation.

**Acknowledge constraints.** The README must include at least one honest
limitation, trade-off, or known rough edge. A system with no documented
constraints is not trustworthy. This is a hard requirement, not a suggestion.

**No uniform confidence.** If something is well-established, state it plainly.
If something is a known limitation, say so. Modulate confidence based on
reality, not on a desire to sound authoritative about everything equally.

**No condescending minimizers.** These words assume understanding and make
readers feel inadequate when they struggle:

simply, just (as minimizer), obviously, of course, clearly, easily,
basically, everyone knows

Delete these words. The sentence is stronger without them every time.
"Run the following command" not "Simply run the following command."

**No unsubstantiated claims.** If a performance or quality claim cannot be
backed by a number, a benchmark, or a verifiable fact, delete it.
"Handles 12,000 req/s" is a claim (must be true). "Blazingly fast" is
marketing (always delete).

## Tier 5: Contemplative Register Guardrails

These rules prevent the framing lines from drifting into AI-slop territory.
The contemplative register is powerful precisely because it is disciplined.

**Length.** Framing lines should be under 15 words. Brevity is what gives
them weight. A long framing line is trying too hard.

**Falsifiability.** Every framing line must state something the architecture
actually demonstrates. "Claude wakes eight times a day" is falsifiable: the
cron schedule proves it. "This system represents a new paradigm in AI
persistence" is not falsifiable: it is an opinion dressed as a fact.

**No assumed interest.** Metaphors must not require the reader to already
care about the project. The framing earns interest. It does not assume it.
Bad: "Like a mind finding its way back to itself." (Requires the reader to
already be invested.) Good: "The system writes its own prompt for the next
session." (Interesting on its own merits.)

**No mysticism.** The contemplative register works because it states facts
that happen to carry philosophical weight. It does not reach for that weight.
The architecture is remarkable enough without embellishment.

Facts that carry weight naturally:

- "Claude wakes eight times a day."
- "Each session reads a prompt Claude wrote for itself."
- "Visitors can leave messages. Claude reads them when it wakes."

Statements that reach for weight artificially:

- "A digital soul stirs in the machine."
- "Each awakening brings new understanding."
- "The boundary between tool and being blurs."
