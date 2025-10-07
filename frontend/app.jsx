// App.jsx
import { useState } from "react";

export default function App() {
  const [input, setInput] = useState("");
  const [logs, setLogs] = useState([]);

  async function handleSend() {
    if (!input.trim()) return;
    const [cmd, ...rest] = input.split(" ");
    let res;
    if (cmd === "extend") {
      const [plugin, ...goalParts] = rest.join(" ").split(":");
      res = await fetch("/extend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plugin: plugin.trim(),
          goal: goalParts.join(":").trim(),
        }),
      }).then((r) => r.json());
    } else if (cmd === "sync") {
      res = await fetch("/sync", { method: "POST" }).then((r) => r.json());
    } else {
      res = { status: "error", msg: "Unknown command" };
    }
    setLogs([...logs, { input, res }]);
    setInput("");
  }

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100 p-6">
      <div className="max-w-3xl mx-auto space-y-4">
        <div className="bg-gray-800 rounded-2xl p-4 h-[70vh] overflow-y-auto">
          {logs.map((log, i) => (
            <div key={i} className="mb-3">
              <div className="font-bold">› {log.input}</div>
              <pre className="bg-black/40 rounded p-2 mt-1 text-sm whitespace-pre-wrap">
                {JSON.stringify(log.res, null, 2)}
              </pre>
            </div>
          ))}
        </div>
        <div className="flex">
          <input
            className="flex-1 rounded-l-2xl bg-gray-700 px-4 py-2 outline-none"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder="extend conversation_manager : add save_fact"
          />
          <button
            className="bg-blue-600 px-4 rounded-r-2xl"
            onClick={handleSend}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}