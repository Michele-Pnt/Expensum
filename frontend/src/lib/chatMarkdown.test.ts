import assert from "node:assert/strict";
import test from "node:test";

import { escapeHtml, renderChatMarkdown } from "./chatMarkdown";

test("escapes every character that could open an HTML tag or attribute", () => {
  assert.equal(escapeHtml(`<img src=x onerror="alert('x')">`), "&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;");
  assert.equal(escapeHtml("Tom & Jerry"), "Tom &amp; Jerry");
});

test("neutralises a script injected through a transaction name before rendering markdown", () => {
  const rendered = renderChatMarkdown("Ho interpretato **<script>alert(1)</script>** di €10.00");
  assert.doesNotMatch(rendered, /<script>/);
  assert.match(rendered, /&lt;script&gt;/);
  assert.match(rendered, /<strong>/);
});

test("still renders bold, italic, inline code and line breaks", () => {
  assert.equal(renderChatMarkdown("**Sushi**"), "<strong>Sushi</strong>");
  assert.equal(renderChatMarkdown("_Ristoranti_"), "<em>Ristoranti</em>");
  assert.equal(renderChatMarkdown("`/spazio`"), "<code>/spazio</code>");
  assert.equal(renderChatMarkdown("riga1\nriga2"), "riga1<br/>riga2");
});
