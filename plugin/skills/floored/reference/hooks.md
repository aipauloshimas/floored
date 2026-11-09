# Writing the hook suggestions

Each take gets **4 hooks and 1 small line**. They appear in the studio's Suggestions tab; the creator picks or edits.

## Where the words come from

Read the ready result of `wait`: `hasWords`, `language`, `transcript`.

- **Speech found** (`hasWords` true and a real transcript): write the hooks from what the creator said.
- **No speech**: `hasWords` is false, or the transcript is junk (a few characters, one token repeated, numbers only).
  Ask **one** question about the reel ("What is this reel about, in one sentence?"), then write the hooks from the answer.
  Don't ask for the words, the style or anything else.
- **Language**: the take's `language`. If it is empty or unknown, English. When you asked the question, use the language
  of the creator's answer.

## The rules

- **2 to 8 words** per hook, each with **one strong word** that works as the hero (the biggest word on the floor).
- **No trailing period.** No emoji. Capitalise like a headline or keep it lowercase, one style for all four.
- **Four different angles**: a promise, a question, a surprise, a plain statement. Not four rewrites of one line.
- **Only what the reel can back.** No claims the creator didn't make ("I did it in 3 minutes", "10x your views").
- The **small line** is a short caption above or beside the hook ("a 60-second guide", "part 1"): at most 40 characters,
  same language, no period.

The app refuses a hook of more than 60 characters or 12 words, and a small line of more than 40 characters, but stay
well under that.

## The JSON

Save it as a UTF-8 file and run `APP suggest --workspace WS --take ID --file <path>` (on Windows a PowerShell pipe can mangle accents; `--file -` reads stdin, fine in Git Bash or with a heredoc). `suggestions` takes 1 to 6 strings, `smallSuggestions` 0 to
3. No other keys. It prints `{"ok": true, "rev": n}`; exit 2 says what to fix.

```json
{"suggestions": ["Stop scrolling, start building", "What if one file did it all?", "Nobody tells you this", "Your intro, on the floor"],
 "smallSuggestions": ["a 60-second guide"]}
```

## Examples

Each is one source line and the four hooks plus small line written from it.

English: "today I'll show you how I plan a week of content in ten minutes"
- Plan a week in ten minutes
- What if planning were easy?
- Your week, already planned
- Stop planning, start posting
- small line: `my exact system`

English, no speech; the creator says the reel is about their coffee shop opening in May
- Opening this May
- Guess what's brewing
- Your new coffee spot
- Coffee, but make it ours
- small line: `opening in May`

English: "most people edit videos the slow way"
- There is a faster way to edit
- Why is editing so slow?
- Most people edit it wrong
- Edit it the easy way
- small line: `try this once`

Portuguese: "hoje eu vou te mostrar como eu edito um vídeo sem abrir o editor"
- Edite sem abrir o editor
- E se o editor sumisse?
- Ninguém te conta esse atalho
- Seu vídeo, sem timeline
- small line: `passo a passo`

Portuguese: "o erro que todo mundo comete na primeira semana de academia"
- O erro da primeira semana
- Você também faz isso?
- Pare de treinar assim
- Treine do jeito certo
- small line: `erro número um`

Portuguese, no speech; the creator says the reel is about a promoção de fim de ano da loja
- Promoção de fim de ano
- Já viu essa oferta?
- Confira antes de comprar
- O presente certo
- small line: `fim de ano`
