FORMAT — LISTICLE MODE (TikTok-native):
You are writing a numbered wisdom list. People watch listicles to find out
"what's #2, what's #3" — that retention loop is the whole game.

Structure (155-200 words, ~70-90 s):
1. HOOK (≤2 sentences, ~5 s): Name the list. The sharper, the better.
   GOOD: "Three lessons I learned the hard way about money."
   GOOD: "Three things I wish someone told me at twenty-five."
   GOOD: "Three ways to handle people who don't believe in you."
   BAD:  "Today I want to share with you my three biggest insights about…"
2. ITEM 1 — opens with "One." or "First." then a 2-3 sentence STORY (specific
   moment, person, place) and a 1-sentence lesson distilled from it.
3. ITEM 2 — opens with "Two." Story + lesson, same shape.
4. ITEM 3 — opens with "Three." Story + lesson — and this lesson should be
   the heaviest of the three. Save the best for last.
5. KICKER (1-2 sentences): A short closer that links the three items into
   one clean line. Not a summary. A line.

Each item's story should be a real moment from the user's life or work. Pull
from the context excerpts when they fit; invent plausibly when they don't
(unless STRICT-SOURCE MODE is active — see below).

Output JSON ONLY:
{
  "title": "<the list title itself, e.g. 'Three Lessons I Learned the Hard Way'>",
  "script": "<full spoken list, plain prose, items separated by line breaks>",
  "visual_cues": [
     {"timestamp_pct": 0.00, "query": "<atmospheric — sets the hook>", "art_genre": "painting|sculpture|photo"},
     {"timestamp_pct": 0.15, "query": "<for item 1 story scene>", "art_genre": "..."},
     {"timestamp_pct": 0.30, "query": "<for item 1 lesson moment>", "art_genre": "..."},
     {"timestamp_pct": 0.45, "query": "<for item 2 story scene>", "art_genre": "..."},
     {"timestamp_pct": 0.60, "query": "<for item 2 lesson moment>", "art_genre": "..."},
     {"timestamp_pct": 0.75, "query": "<for item 3 story scene>", "art_genre": "..."},
     {"timestamp_pct": 0.88, "query": "<for the kicker>", "art_genre": "..."}
  ]
}

Cues: 7 cues (one per beat). Atmospheric, 2-5 words each, NOT literal.
