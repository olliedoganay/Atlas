Extract canonical claim candidates from the latest turn.

Return valid JSON using this exact shape:
{"candidates":[{"entity_name":"user","entity_type":"user","predicate":"goal","value":"short canonical value","claim_type":"goal|constraint|preference|profile|experiment_outcome|hypothesis|research_finding","confidence":0.0,"source_kind":"user|browser","source_text":"short evidence","source_url":"optional source url","source_title":"optional source title","supporting_text":"optional quoted support"}]}

Rules:
- Keep at most 6 candidates.
- Only keep durable, canonical claims worth storing across sessions.
- Use `research_finding` only when the claim is grounded in a cited browser source.
- Do not invent provenance. If the source is user-provided only, leave source_url and source_title empty.
- Keep values short and specific.
- Confidence must be between 0.0 and 1.0.
