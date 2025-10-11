export type ChatResponse = {
  status: string;
  message?: string;
  assistant_message?: string;
  data?: any;
};

export async function postChat(message: string): Promise<ChatResponse> {
  const res = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message })
  });
  return res.json();
}

export async function getContext(): Promise<{ status: string; data?: any }> {
  const res = await fetch("/context");
  return res.json();
}