import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const PROVIDER = "m365-copilot";

const MODELS = [
  {
    id: "default",
    name: "M365 Copilot",
    reasoning: false as const,
    input: ["text" as const],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 128000,
    maxTokens: 8192,
  },
];

export default function (pi: ExtensionAPI) {
  function register(sessionId?: string) {
    pi.registerProvider(PROVIDER, {
      baseUrl: "http://127.0.0.1:8787/v1",
      apiKey: "unused",
      api: "openai-completions",
      // Stable per-pi-session key so the proxy can skip hash heuristics.
      headers: sessionId ? { "X-Session-Id": sessionId } : undefined,
      models: MODELS,
    });
  }

  register();

  pi.on("session_start", async (_event, ctx) => {
    register(ctx.sessionManager.getSessionId());
  });
}
