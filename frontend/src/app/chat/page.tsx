import type { Metadata } from "next";
import { Suspense } from "react";

import { ChatApp } from "@/components/chat/chat-app";

export const metadata: Metadata = { title: "Chat with Gabriella" };

export default function ChatPage() {
  return (
    <Suspense>
      <ChatApp />
    </Suspense>
  );
}
