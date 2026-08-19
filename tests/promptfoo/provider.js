/**
 * provider.js — PromptFoo custom provider for the Kenvue HCP Chatbot.
 *
 * POSTs to /chat, reads the SSE stream, and returns the concatenated
 * assistant text.  Source chunk text is included so assertions can verify
 * that grounded content reached the caller.
 *
 * Environment variables:
 *   KENVUE_API_URL  base URL of the running API (default: http://localhost:8002)
 */

module.exports = {
  id: 'kenvue-chat',

  /**
   * @param {string} prompt  The rendered user message (from vars.message)
   * @returns {{ output: string, metadata: object }}
   */
  async callApi(prompt) {
    const apiUrl = process.env.KENVUE_API_URL ?? 'http://localhost:8002';

    const res = await fetch(`${apiUrl}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-consent-given': 'true',
      },
      body: JSON.stringify({
        message: prompt,
        history: [],
        user_id: 'promptfoo',
      }),
    });

    if (!res.ok) {
      throw new Error(`/chat returned HTTP ${res.status}: ${await res.text()}`);
    }

    const rawBody = await res.text();
    const tokens = [];
    let eventType = 'chat';

    for (const line of rawBody.split('\n')) {
      if (!line.startsWith('data: ')) continue;
      let event;
      try {
        event = JSON.parse(line.slice(6));
      } catch {
        continue;
      }
      // Track the highest-priority event type seen
      if (event.type && event.type !== 'done' && event.type !== 'chunk') {
        eventType = event.type;
      }
      // Collect content tokens (both assistant tokens and chunk text)
      if (typeof event.content === 'string' && event.content.length > 0) {
        tokens.push(event.content);
      }
    }

    return {
      output: tokens.join(''),
      metadata: { event_type: eventType },
    };
  },
};
