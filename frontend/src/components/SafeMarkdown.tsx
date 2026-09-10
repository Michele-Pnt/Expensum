import { createElement } from "react";

import { renderChatMarkdown } from "@/lib/chatMarkdown";

type SafeMarkdownProps = {
  as?: "p" | "span";
  className?: string;
  text: string;
};

/**
 * Rende il Markdown minimale delle conversazioni in un solo punto controllato.
 * `renderChatMarkdown` esegue l'escaping dell'HTML prima di generare i tag consentiti.
 */
export function SafeMarkdown({ as = "span", className, text }: SafeMarkdownProps) {
  return createElement(as, {
    className,
    dangerouslySetInnerHTML: { __html: renderChatMarkdown(text) },
  });
}
