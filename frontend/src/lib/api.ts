export type ChatResponse = { reply?: string } & Record<string, any>;

export async function postChat(text: string): Promise<ChatResponse> {
  // The gold backend expects { text }, but also tolerates message/prompt/content.
  const res = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text })
  });
  return res.json();
}