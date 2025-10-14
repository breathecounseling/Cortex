import React from "react";
import ChatPane from "./components/ChatPane";

export default function App() {
  return (
    <div className="grid grid-cols-1 h-screen bg-white">
      <section className="flex flex-col">
        <header className="border-b p-4">
          <h1 className="text-xl font-semibold text-gray-800">Echo · Chat</h1>
        </header>
        <main className="flex-1 overflow-hidden">
          <ChatPane />
        </main>
      </section>
    </div>
  );
}