export function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  const entries = Object.keys(value).filter((key) => value[key] !== undefined).sort();
  return `{${entries.map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
}

const toHex = (bytes) => [...new Uint8Array(bytes)].map((value) => value.toString(16).padStart(2, '0')).join('');

export async function verifyEvidenceChain(chain, subtle = globalThis.crypto?.subtle) {
  const records = Array.isArray(chain) ? chain : chain?.records;
  if (!Array.isArray(records) || records.length === 0) return { status: 'incomplete', message: 'No full evidence records were provided.' };
  if (!subtle) return { status: 'incomplete', message: 'Web Crypto SHA-256 is unavailable in this browser context.' };
  let previousHash = null;
  for (let index = 0; index < records.length; index += 1) {
    const item = records[index];
    if (!item || typeof item.recordId !== 'string' || !item.record || typeof item.record !== 'object' || typeof item.hash !== 'string') {
      return { status: 'incomplete', index, recordId: item?.recordId || null, message: `Record ${index + 1} is missing required chain fields.` };
    }
    if ((item.previousHash || null) !== previousHash) {
      return { status: 'broken', index, recordId: item.recordId, message: `The previous-hash link is broken at record ${item.recordId}.` };
    }
    const canonicalRecord = canonicalJson({ recordId: item.recordId, record: item.record, previousHash: item.previousHash || null });
    const actualHash = toHex(await subtle.digest('SHA-256', new TextEncoder().encode(canonicalRecord)));
    if (actualHash !== item.hash.toLowerCase()) return { status: 'modified', index, recordId: item.recordId, expectedHash: item.hash, calculatedHash: actualHash, message: `Record ${item.recordId} does not match its stored SHA-256 hash.` };
    previousHash = actualHash;
  }
  if (Number.isInteger(chain?.expectedCount) && chain.expectedCount !== records.length) {
    return { status: 'missing', message: `The export contains ${records.length} records; the chain metadata expects ${chain.expectedCount}.`, expectedCount: chain.expectedCount, actualCount: records.length };
  }
  if (chain?.checkpoint?.lastHash && chain.checkpoint.lastHash.toLowerCase() !== previousHash) {
    return { status: 'broken', recordId: records.at(-1).recordId, message: 'The last record does not match the supplied checkpoint hash.' };
  }
  return { status: 'verified', count: records.length, lastHash: previousHash, signedCheckpoint: Boolean(chain?.checkpoint?.signature && chain?.checkpoint?.publicKey), message: `All ${records.length} records and previous-hash links match.` };
}
