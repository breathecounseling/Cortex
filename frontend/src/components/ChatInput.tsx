import React from "react";

export default function ChatInput({
  value,
  onChange,
  onSend,
  disabled
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  disabled: boolean;
}) {
  return (
    <div className="border-t p-3 flex gap-2 bg-gray-50">
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSend();
          }
        }}
        placeholder="Type a message..."
        className="flex-1 resize-none rounded-lg border p-2 focus:outline-none focus:ring-2 focus:ring-cortexBlue"
        rows={2}
      />
      <button
        onClick={onSend}
        disabled={disabled}
        className="px-4 py-2 bg-cortexBlue text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
      >
        {disabled ? "…" : "Send"}
      </button>
    </div>
  );
}