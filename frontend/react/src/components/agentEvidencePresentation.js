function safeScalar(value) {
  return ["string", "number"].includes(typeof value)
    ? String(value).trim()
    : "";
}

function safeUrlLabel(value) {
  const source = safeScalar(value);
  if (!/^https?:\/\//i.test(source)) return "";
  try {
    const url = new URL(source);
    const path = url.pathname === "/" ? "" : url.pathname.replace(/\/$/, "");
    return `${url.hostname}${path}`;
  } catch {
    return "";
  }
}

export function evidenceReferenceLabel(reference, index = 0) {
  const displayLabel = safeScalar(reference?.displayLabel);
  if (displayLabel) return displayLabel.slice(0, 120);
  const filename = safeScalar(reference?.filename || reference?.title);
  if (filename) {
    const safeUrl = safeUrlLabel(filename);
    return (safeUrl || filename).slice(0, 120);
  }
  const urlLabel = safeUrlLabel(reference?.url || reference?.href);
  if (urlLabel) return urlLabel.slice(0, 120);
  const chunkId = safeScalar(reference?.chunkId || reference?.chunk_id);
  return chunkId ? `片段 #${chunkId.slice(0, 40)}` : `来源 ${index + 1}`;
}

export function evidenceReferences(run = null) {
  const artifacts = Array.isArray(run?.artifacts) ? run.artifacts : [];
  const seen = new Set();
  return artifacts
    .filter((artifact) => artifact?.artifactType === "reference")
    .map((reference, index) => ({
      id: safeScalar(
        reference?.artifactId
        || reference?.chunkId
        || reference?.chunk_id
        || reference?.eventId,
      ) || `reference-${index}`,
      label: evidenceReferenceLabel(reference, index),
      score: Number.isFinite(Number(reference?.score))
        ? Math.max(0, Math.min(100, Math.round(Number(reference.score) * 100)))
        : null,
      source: reference,
      excerpt: safeScalar(reference?.excerpt),
    }))
    .filter((reference) => {
      const key = `${reference.id}:${reference.label}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}
