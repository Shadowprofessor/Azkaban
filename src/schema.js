/**
 * GhostPrint frontend contract.
 * Keep property names aligned with the frozen team contract in the frontend PRD.
 * @typedef {'email'|'phone'|'imei'|'adid'|'gps'|'contact'|'clipboard'} PiiType
 * @typedef {{type:PiiType, redacted:string, confidence:number}} PiiHit
 * @typedef {{id:string,ts:string,app:string,host:string,method:string,path:string,ip:string,country:string,company:string|null,tracker:{name:string,category:string}|null,decrypted:boolean,pii:PiiHit[],severity:number,tcf:{vendors:number,purposes:string[]}|null,bytes:number}} Flow
 * @typedef {{source:string,section:string,url:string}} Citation
 * @typedef {{flowId:string,status:'compliant'|'questionable'|'violation',reasoning:string,citations:Citation[]}} Verdict
 * @typedef {{total:number,categories:{name:string,value:number}[]}} Score
 */

export const MAX_FLOWS = 2000;
export const AGENT_SOCKET_DEFAULT = 'ws://localhost:8787';

export const formatBytes = (bytes = 0) => bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

export function validateInbound(message) {
  if (!message || typeof message !== 'object' || typeof message.type !== 'string') return false;
  if (!['status', 'flow', 'verdict', 'score', 'blocklist', 'evidence', 'error'].includes(message.type)) return false;
  if (!message.data || typeof message.data !== 'object') return false;
  if (message.type === 'flow') {
    const f = message.data;
    return typeof f.id === 'string' && typeof f.ts === 'string' && typeof f.app === 'string' && typeof f.host === 'string' && Array.isArray(f.pii) && typeof f.severity === 'number';
  }
  return true;
}
