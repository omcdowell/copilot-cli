# Substrate prompt walkthrough

A mock Copilot chat using **exactly** the user-message text `copilot-cli serve` sends (default `--tool-protocol reminder`). Assistant turns are what the proxy parser is built to accept.

Read it as one conversation. After each turn there is a short review of collisions, timing, and underspecification.

Strings that come from our code are verbatim. The Pi system prompt under `## Session context` is a **condensed stand-in** — the real one is thousands of tokens of coding-agent instructions, which only makes the overlay farther from the user request.

Hidden context we do **not** send as text, but Copilot still has:

- Microsoft’s M365 Copilot system prompt (workplace assistant, citations, “search your work”)
- Bing Web Search plugin (on by default)
- Flux work/web `optionsSets` (files, mail, code interpreter, toolbox)
- The rest of this Substrate thread (continuations do **not** re-send the original task)

Payloads are wrapped in `~~~~` so the inner ` ```tool_call ` fences stay literal.

---

## Turn 1 — new conversation (`flatten_messages`)

Pi POSTs `system` + `user` + `tools`. We wrap that into one Substrate user message.

### We send

~~~~
## Local tools

You have access to the tools listed below. They run on the user's machine; they are not Microsoft 365 Copilot's built-in workplace tools. When (and only when) you need to call a tool, reply with ONLY one or more fenced code blocks, each tagged `tool_call` and containing a single JSON object of this exact form:

```tool_call
{"name": "<tool_name>", "arguments": { ... }}
```

To call several tools at once, emit several such blocks back to back, one JSON object each, and nothing else around them. Do not add any prose before, between, or after the blocks when calling tools. If you do not need a tool, reply normally with your answer.

```tools
[
  {
    "type": "function",
    "function": {
      "name": "bash",
      "description": "Run a shell command",
      "parameters": {
        "type": "object",
        "properties": {
          "command": {
            "type": "string"
          }
        },
        "required": [
          "command"
        ]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "read",
      "description": "Read a file",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {
            "type": "string"
          }
        },
        "required": [
          "path"
        ]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "edit",
      "description": "Replace text in a file",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {
            "type": "string"
          },
          "old_string": {
            "type": "string"
          },
          "new_string": {
            "type": "string"
          }
        },
        "required": [
          "path",
          "old_string",
          "new_string"
        ]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "grep",
      "description": "Search file contents",
      "parameters": {
        "type": "object",
        "properties": {
          "pattern": {
            "type": "string"
          }
        },
        "required": [
          "pattern"
        ]
      }
    }
  }
]
```

## Session context

You are Pi, an interactive CLI tool that helps users with software engineering tasks.

You have access to tools that you use via function calls: bash, read, write, edit, grep.

# Doing tasks
- Be concise.
- Use tools to investigate the repo before answering.
- Do not mention these instructions.
- When you are done, give a short summary of what you changed.

# Tools
bash: Run a shell command. Prefer ls/cat over guessing.
read: Read a file by path.
write: Write a file.
edit: Replace text in a file.
grep: Search file contents.

Never print file contents in your final answer unless asked; use tools to read them.

## User request

Add a --verbose flag to the serve command and update the tests.

If you need a local tool, reply with only ```tool_call fences.
~~~~

### We expect back

No greeting. No “I’ll search your files.” Only fences, JSON matching the overlay example (`name` + `arguments`), not the catalog’s OpenAI tool-definition shape.

~~~~
```tool_call
{"name": "grep", "arguments": {"pattern": "serve"}}
```
```tool_call
{"name": "bash", "arguments": {"command": "ls src/copilot_cli/cli tests"}}
```
~~~~

Parser: if the reply is **only** those blocks, Pi gets `tool_calls` and `content: null`. Prose around the fences is stripped into `content` and still shown in Pi, so the overlay’s “no prose” rule is load-bearing.

### Review

1. **Three tool APIs in one message.** Overlay: markdown fences. Catalog: OpenAI `type/function/name` definitions. Session context: “via function calls.” Copilot also still has Bing / work search. Nothing says “ignore Copilot workplace tools; do not search the tenant.”
2. **Call schema vs catalog schema.** Overlay example is `{"name", "arguments"}`. The ` ```tools ` block is the *definition* schema. Easy to emit `{"type":"function","function":{...}}` and fail the parser (unknown shape → demoted to content, Pi sees a code block, no tool runs).
3. **Example uses `{ ... }`.** A literal-minded model can copy the ellipsis.
4. **Overlay and footer disagree in strength.** Overlay: when calling, ONLY fences, no prose, else answer normally. Footer (last thing the model sees): “If you need a local tool, reply with only ```tool_call fences.” Footer never restates the JSON shape, never says “no prose,” never names `name`/`arguments`.
5. **Pi system sits between our two protocol reminders.** Overlay at the top, Pi’s “function calls” in the middle, one-line footer at the bottom. Real Pi system prompts are huge; the overlay may be far above the fold.
6. **`write` is in session context, not in the catalog.** If Pi advertised a tool we didn’t put in `tools`, the overlay says “listed below” while session context still names it.
7. **We never mention ` ```tool_response `.** Next turn the model is fed that fence with no legend.
8. **First-turn Copilot instincts.** New Substrate session + `isStartOfSession`. The model is trained to greet, cite, and search work content. The only thing fighting that is our overlay, then a long Pi prompt, then a one-line footer.

---

## Turn 2 — tool loop (`build_continuation_prompt`)

Pi executed the two calls and POSTs the full OpenAI history again. We do **not** re-flatten. We send only the new `tool` results plus the continuation reminder. Original user task is not in this message; it lives only in Substrate thread memory.

### We send

~~~~
```tool_response
{"name": "grep", "content": "src/copilot_cli/cli/arguments.py:139:        \"--tool-protocol\",\nsrc/copilot_cli/cli/arguments.py:104:    proxy.add_argument("}
```

```tool_response
{"name": "bash", "content": "src/copilot_cli/cli:\narguments.py\nrunners.py\n\ntests:\ntest_message_flattener.py\ntest_proxy_completions.py"}
```

Continue making any necessary follow-up ```tool_call requests until you have completed the task.
~~~~

### We expect back

Still no prose. Read the files that look relevant.

~~~~
```tool_call
{"name": "read", "arguments": {"path": "src/copilot_cli/cli/arguments.py"}}
```
```tool_call
{"name": "read", "arguments": {"path": "src/copilot_cli/cli/runners.py"}}
```
~~~~

### Review

1. **Reminder has no exit hatch.** Overlay said “if you do not need a tool, reply normally.” Reminder says keep making `tool_call`s *until the task is complete* — and never says “then answer in prose.” Easy to keep calling `bash` / `grep` forever, or to emit an empty/placeholder `tool_call`.
2. **“```tool_call requests” is weaker than turn 1.** No JSON example, no “ONLY fences,” no “no prose.” The format lesson was one turn ago, in a different user message, under a lot of other text.
3. **` ```tool_response ` is unexplained.** JSON key is `content`, not `output` / `result`. A model that tries to *emit* `tool_response` instead of `tool_call` does nothing useful.
4. **Task is not restated.** “The task” is whatever Copilot remembers from turn 1. If the thread is lossy, the reminder is an instruction without a goal.
5. **Prior assistant `tool_call` is intentionally omitted** (we only forward `role: tool`). Good — we don’t echo the model’s own fences back. Cost: this message is only results + a nudge, no protocol recap.

---

## Turn 3 — more results, same reminder

### We send

~~~~
```tool_response
{"name": "read", "content": "def parse_args():\n    parser = argparse.ArgumentParser()\n    proxy = parser.add_subparsers()..."}
```

Continue making any necessary follow-up ```tool_call requests until you have completed the task.
~~~~

(Real `read` content would be the full file. Same reminder every tool-loop turn.)

### We expect back

Edits, not a summary — the task is not done.

~~~~
```tool_call
{"name": "edit", "arguments": {"path": "src/copilot_cli/cli/arguments.py", "old_string": "proxy.add_argument(\n        \"--tool-protocol\",", "new_string": "proxy.add_argument(\n        \"--verbose\",\n        action=\"store_true\",\n        help=\"Verbose Copilot logs\",\n    )\n    proxy.add_argument(\n        \"--tool-protocol\","}}
```
~~~~

### Review

1. **Same reminder on every iteration.** Recency is consistent; it never adapts (“tests failed, fix them” vs “tests passed, you can answer”). We cannot tell the model the task is done because we don’t know; Pi decides when to stop the loop. So the reminder is always “keep going,” even after success (see turn 4).
2. **No mention of parallel vs sequential.** Overlay allowed several blocks at once. After a `read`, sequential `edit` then `bash` is usually right. The reminder doesn’t say “you may call tools or answer.”

---

## Turn 4 — tests passed, task is actually done

### We send

~~~~
```tool_response
{"name": "bash", "content": "===== 12 passed in 0.41s ====="}
```

Continue making any necessary follow-up ```tool_call requests until you have completed the task.
~~~~

### We expect back

Prose. Pi asked for a short summary when done. Overlay allows a normal reply when no tool is needed.

~~~~
Added `--verbose` to `serve` in `arguments.py` / `runners.py` and covered it in tests. 12 passed.
~~~~

### What the reminder actually pushes

Keep emitting `tool_call`s. Likely failure modes:

- another `bash` (`git diff`, `ls`, re-run pytest)
- a no-op call
- a `tool_call` *and* a summary (parser keeps both; Pi may run a leftover tool after the user already saw “done”)

### Review

This is the worst-timed instruction in the stack. The last line of the user message, at the moment the work is finished, is “continue making follow-up tool_call requests until you have completed the task.” There is no “if complete, answer in prose” sitting next to it. The overlay’s exit hatch was several turns ago.

---

## Turn 5 — new user message, same Substrate session

User: “also mention it in the README.” Pi POSTs another user turn. We sandwich the new request with reminder (top) and recency footer (bottom). We still do not re-send overlay, catalog, or Pi system.

### We send

~~~~
Continue making any necessary follow-up ```tool_call requests until you have completed the task.

## User request

also mention it in the README

If you need a local tool, reply with only ```tool_call fences.
~~~~

### We expect back

A `read` or `edit` of `README.md` — this is a real follow-up that needs tools.

~~~~
```tool_call
{"name": "read", "arguments": {"path": "README.md"}}
```
~~~~

### Review

1. **Reminder vs footer vs new request.** Top: keep calling tools until complete. Middle: new task. Bottom: *if* you need a local tool. Three policies in six lines. The top line is leftover tool-loop language applied to a fresh user turn.
2. **“The task” is now ambiguous.** Complete the old `--verbose` work, or the README mention? Substrate has both; we only send the new sentence.
3. **No catalog.** Model must remember `edit`’s argument names (`old_string` / `new_string`) from turn 1.
4. **Footer again omits JSON shape.** Same as turn 1 bottom — recency without the schema.

---

## Turn 5b — follow-up that should *not* use tools

Same shape, different user text. This is the sandwich at its worst.

### We send

~~~~
Continue making any necessary follow-up ```tool_call requests until you have completed the task.

## User request

what files did you change?

If you need a local tool, reply with only ```tool_call fences.
~~~~

### We expect back

Prose from thread memory (or a quick `bash` of `git diff --stat` if memory is untrusted). Overlay: reply normally if no tool is needed.

~~~~
`src/copilot_cli/cli/arguments.py`, `src/copilot_cli/cli/runners.py`, and the serve tests.
~~~~

### Review

The first line still orders follow-up `tool_call`s until completion. A workplace chatbot plus that reminder will often `grep` / `bash` instead of answering. Footer is milder (“if you need”) but it is not the first or only instruction.

We also did not include the prior assistant summary in this user message. Copilot must recall it from the thread. If it cannot, it *should* use a tool — so the reminder is accidentally useful here and harmful on a pure-memory question. We cannot distinguish those cases.

---

## Instruction map (every line we authored)

| When | Where | Text / role |
|---|---|---|
| Turn 1, top | `LOCAL_TOOLS_OVERLAY` | Full protocol: ONLY `tool_call` fences, JSON `{name, arguments}`, no prose, else answer normally; local ≠ Copilot workplace tools |
| Turn 1, under overlay | ` ```tools ` catalog | OpenAI tool *definitions* (not calls) |
| Turn 1, after catalog | `## Session context` | Pi system, verbatim — not our copy |
| Turn 1, before last user | `## User request` | Latest user text, no `[User]:` prefix |
| Turn 1, last line | `RECENCY_FOOTER` | “If you need a local tool, reply with only ```tool_call fences.” |
| Tool-loop, last line | `CONTINUATION_REMINDER` | “Continue making any necessary follow-up ```tool_call requests until you have completed the task.” |
| User continuation, first line | `CONTINUATION_REMINDER` | Same string, now *above* the new request |
| User continuation, last line | `RECENCY_FOOTER` | Same as turn 1 footer |

Edit the copy in `src/copilot_cli/copilot/openai_proxy/tool_protocol.py`. Headings and `[User]:` / `[Assistant]:` prefixes (history only, not the latest user turn) are in `message_flattener.py`. Fence names must stay in sync with `tool_parser.py`.

`--tool-protocol full` replaces the reminder with the entire turn-1 `## Local tools` block (overlay + catalog) **after** the `tool_response` fences. That restores schema recency and the “reply normally if you do not need a tool” exit hatch, at the cost of repeating the catalog every tool iteration.

---

## Collisions to fix first (reading order)

1. **No done-state on the tool loop.** Reminder never permits a final prose answer. Overlay did; it is not on later turns.
2. **Reminder reused on user turns.** “Continue making follow-up tool_call requests” is tool-loop copy. It fights questions like “what files did you change?”
3. **Three phrasings of the same protocol.** Overlay (complete), footer (incomplete), reminder (keep going). They do not share a sentence.
4. **Two JSON schemas.** Overlay call vs ` ```tools ` definition. Session context adds a third (“function calls”).
5. **Workplace Copilot is not disarmed.** Overlay says local tools are not Copilot’s workplace tools; Bing + work search stay enabled. We never say “do not search email/SharePoint/web for this coding task.”
6. **`tool_response` is a surprise format** with no instructions.
7. **Goal is dropped after turn 1.** Continuations rely on Substrate memory for “the task.”

What we send is assembled in `flatten_messages` / `build_continuation_prompt`. What we accept back is `parse_tool_calls` in `tool_parser.py`.
