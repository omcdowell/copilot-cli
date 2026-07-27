import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.registerProvider("m365-copilot", {
    baseUrl: "http://127.0.0.1:8787/v1",
    apiKey: "unused",
    api: "openai-completions",
    models: [
      {
        id: "default",
        name: "M365 Copilot",
        reasoning: false,
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 128000,
        maxTokens: 8192,
      },
    ],
  });
}
