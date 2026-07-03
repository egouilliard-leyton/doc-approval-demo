// A tiny fetch-based Server-Sent Events reader. The browser's EventSource can't
// POST a body, so we parse the `text/event-stream` off the response body stream
// ourselves: buffer bytes, split on the blank-line frame delimiter, and yield
// the JSON payload of every `data:` line.
export async function* readSSE(response: Response): AsyncGenerator<unknown> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Frames are separated by a blank line; keep the trailing partial frame
      // in the buffer until its delimiter arrives.
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        for (const line of frame.split("\n")) {
          if (line.startsWith("data: ")) {
            yield JSON.parse(line.slice(6));
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
