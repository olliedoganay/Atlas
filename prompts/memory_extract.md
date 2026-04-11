Extract only durable long-term memories from the latest turn.

Return valid JSON using this exact shape:
{"candidates":[{"category":"preference|profile|goal|constraint|experiment_outcome","value":"short durable memory","confidence":0.0}]}

Rules:
- Keep at most 5 candidates.
- Only keep durable items that should survive across sessions.
- Ignore temporary chatter, greetings, and one-off task phrasing.
- The value must be short, stable, and specific.
- Confidence must be between 0.0 and 1.0.
