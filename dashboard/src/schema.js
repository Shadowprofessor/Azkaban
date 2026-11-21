/**
 * GhostPrint frontend contract.
 * Keep property names aligned with the frozen team contract in the frontend PRD.
 * @typedef {'email'|'phone'|'imei'|'adid'|'gps'|'contact'|'clipboard'} PiiType
 * @typedef {{type:PiiType, redacted:string, confidence:number, correlation?:{scheme:'hmac-sha256',pseudonymized:true,fingerprint:string,confidence?:number}}} PiiHit
 * @typedef {{id:string,ts:string,app:string,host:string,method:string,path:string,ip:string,country:string,company:string|null,tracker:{name:string,category:string}|null,decrypted:boolean,pii:PiiHit[],severity:number,tcf:{vendors:number,purposes:string[]}|null,bytes:number, idle?:{state:'idle'|'active',sessionId:string}, traffic?:{uploadBytes?:number,downloadBytes?:number,protocol?:string,durationMs?:number}, process?:{pid?:number,name?:string}}} Flow
 * @typedef {{source:string,section:string,url:string}} Citation
 * @typedef {{flowId:string,status:'compliant'|'questionable'|'violation',reasoning:string,citations:Citation[]}} Verdict
 * @typedef {{total:number,categories:{name:string,value:number}[]}} Score
 *
 * Optional flow fields above are additive integration extensions. The frozen
 * core flow remains valid without them. Idle classification, process metadata,
 * byte direction, and keyed identifier fingerprints must come from the local
 * audit agent; the browser cannot infer them reliably.
 *
 * Evidence chain export extension:
 * evidence.chain = { expectedCount?, records:[{recordId,record,previousHash,hash}], checkpoint?:{lastHash} }
 * hash is SHA-256 of canonical JSON {recordId,record,previousHash}. Signed
 * checkpoints need separate agent-side key management and are not implied here.
 */

export const MAX_FLOWS = 2000;
// The agent binds loopback only (azkaban_agent/safety.require_loopback).
export const AGENT_SOCKET_DEFAULT = 'ws://127.0.0.1:8787';

export const formatBytes = (bytes = 0) => bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

/**
 * Validates a message AFTER src/adapter.js has normalised it into {type, data}.
 * Raw agent messages never reach here: the agent speaks lib/live/protocol.ts (frozen),
 * which names each payload after its type, and adapter.normalise converts it.
 */
export function validateInbound(message) {
  if (!message || typeof message !== 'object' || typeof message.type !== 'string') return false;
  if (!INBOUND_KINDS.includes(message.type)) return false;
  if (!message.data || typeof message.data !== 'object') return false;
  if (message.type === 'flow') {
    const f = message.data;
    return typeof f.id === 'string' && typeof f.ts === 'string' && typeof f.app === 'string' && typeof f.host === 'string' && Array.isArray(f.pii) && typeof f.severity === 'number';
  }
  return true;
}

export const INBOUND_KINDS = ['status', 'flow', 'verdict', 'score', 'blocklist', 'evidence', 'insight', 'error'];
export const MAX_INSIGHTS = 200;
