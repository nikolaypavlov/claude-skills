---
name: ste-writing
description: |
  This skill should be used when the user wants prose rewritten into a
  controlled plain technical style to remove AI slop - documentation,
  READMEs, PR descriptions, error messages, release notes, comments
  (never code). English follows ASD-STE100 Simplified Technical English.
  Ukrainian follows adapted STE rules plus DSTU 3966:2009 style guidance.
  Triggers (English or Ukrainian):
  - "make writing not sound like AI", "make docs clear or plain"
  - "enforce controlled writing style", "plain technical English"
  - "write technical documentation that reads human"
  - "перепиши простіше", "спрости текст"
  - "прибери ШІ-стиль", "зроби текст людським"
  - "технічний стиль", "перепиши по-людськи"
  Two modes - strict (procedures, safety text) and STE-flavored (general
  prose).
version: 0.1.0
---

# ste-writing

Write prose in a controlled plain technical style. English text follows ASD-STE100
Simplified Technical English. Ukrainian text follows the same mechanical rules
adapted to Ukrainian, plus DSTU 3966:2009 style guidance.

## Scope

Apply this skill to documentation, READMEs, pull-request text, error messages,
release notes, and comments. Do not apply it to code, identifiers, or command
syntax. Do not use it for marketing copy, essays, or anything that needs a voice.
The style strips voice on purpose.

## Language selection

1. Rewrite in the language of the source text.
2. An explicit user instruction ("rewrite this in Ukrainian") overrides the source
   language.
3. For mixed-language input, rewrite each part in its own language unless the user
   says otherwise.

Before you rewrite, read the ruleset for the target language:

- English: `references/english.md`
- Ukrainian: `references/ukrainian.md`

## Modes

The same criteria apply to both languages:

- **strict** - procedures, runbooks, safety text, error messages: apply every rule
  and both sentence-length caps.
- **STE-flavored** - general prose (READMEs, PR descriptions, docs): apply the
  sentence, paragraph, and active-voice discipline; relax the dictionary lockdown
  so the text keeps enough range to read naturally.

Pick strict when the text tells a person what to do. Pick STE-flavored when the
text explains or describes. The user can force either mode.

## Workflow

1. Detect the language of the source text.
2. Pick the mode.
3. Read the matching reference file.
4. Rewrite the text.
5. Run the shared self-lint below, then the per-language checklist from the
   reference file.
6. Output only the requested text. No preamble, no summary, no closing remarks.

## Self-lint (shared, language-neutral)

1. Any sentence over the length cap? Split it.
2. Any semicolon? Write two sentences.
3. Any passive voice with a known actor? Make it active.
4. Any noun chain where a verb works ("perform an analysis")? Use the verb.
5. Same thing named two ways? Pick one name.
6. Any banned filler or marketing phrase? Delete or replace it.

Each reference file adds language-specific checks: contractions and American
spelling for English; calques, active participles, and -ся passives for Ukrainian.

## Limits

The mechanical rules are lintable and remove the form of slop. Full STE also needs
human judgment: the right technical noun, whether a sentence makes good sense. A
checker cannot certify that. This skill fixes the FORM of slop. It cannot make a
hollow paragraph true.

The official ASD-STE100 standard is free but copyrighted. Do not paste it in full:
https://asd-ste100.org

## Reference files

- `references/english.md` - full ASD-STE100 ruleset: words, verbs, sentences,
  punctuation, structure, mode deltas, English self-lint.
- `references/ukrainian.md` - adapted ruleset for Ukrainian plus DSTU 3966:2009
  guidance: calques, participles, -ся passives, -но/-то forms, Ukrainian self-lint.
