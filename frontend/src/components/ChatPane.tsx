import React, { useEffect, useRef, useState } from "react";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import { postChat } from "../lib/api";

type Msg = { role: "user" | "assistant" | "system"; text: string };

export default function ChatPane() {
  const [msgs, setMsgs] = useState<Msg[]>([
    { role: "assistant", text: "Hi! I’m Echo. I'm here to make your life easier."}
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs]);

  async function send() {
    const text = input.trim();
    if (!text) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", text }]);
    setBusy(true);
    try {
      const res = await postChat(text);
      const reply = (res && (res.reply ?? res.assistant_message ?? res.message)) || "Okay.";
      setMsgs((m) => [...m, { role: "assistant", text: reply }]);
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "system", text: `⚠️ ${e?.message || "Network error"}` }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 bg-gray-50 scrollbar-thin">
        {msgs.map((m, i) => <ChatMessage key={i} role={m.role} text={m.text} />)}
      </div>
      <ChatInput value={input} onChange={setInput} onSend={send} disabled={busy} />
    </div>
  );
}