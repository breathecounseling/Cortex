import React from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github.css";

export default function ChatMessage({
  role,
  text
}: {
  role: string;
  text: string;
}) {
  const isUser = role === "user";
  const bubble =
    isUser ? "bg-cortexBlue text-white" : "bg-white text-gray-900";
  const align = isUser ? "justify-end" : "justify-start";

  return (
    <div className={`flex ${align} my-2`}>
      <div
        className={`max-w-[70ch] rounded-2xl px-4 py-2 shadow-sm prose prose-sm sm:prose-base ${bubble}`}
      >
        <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
          {text}
        </Markdown>
      </div>
    </div>
  );
}