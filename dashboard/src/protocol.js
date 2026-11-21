// Outbound commands. Shapes come from lib/live/protocol.ts, which is FROZEN: the agent
// takes `blocklist.action`, not a format, and `start` carries no payload. `configure_idle`
// is an additive extension from the nirmit branch, implemented by the v1 agent.
// Kept as a re-export so existing imports of OUTBOUND keep working.
import { COMMANDS } from './adapter';

export const OUTBOUND = COMMANDS;
export const INBOUND_TYPES = ['status', 'flow', 'verdict', 'score', 'blocklist', 'evidence', 'insight', 'error'];
