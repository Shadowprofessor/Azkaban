import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { availableCorrelationCategories, deriveIdentityCorrelations, deriveIdleActivity } from '../src/privacyFeatures.js';
import { canonicalJson, verifyEvidenceChain } from '../src/integrity.js';
import { LEGAL_REFERENCES } from '../src/legalReferences.js';

const digest = async (value) => [...new Uint8Array(await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))].map((byte)=>byte.toString(16).padStart(2,'0')).join('');

test('idle metrics include only agent-labelled idle flows with a session id', () => {
  const result = deriveIdleActivity([
    { id:'idle-1', ts:'2026-01-01T10:00:00Z', app:'Maps', host:'geo.example', idle:{state:'idle',sessionId:'s1'}, traffic:{uploadBytes:120}, pii:[{type:'gps'}] },
    { id:'idle-2', ts:'2026-01-01T10:01:00Z', app:'Maps', host:'geo.example', idle:{state:'idle',sessionId:'s1'}, traffic:{uploadBytes:80} },
    { id:'active-1', ts:'2026-01-01T10:02:00Z', app:'Maps', host:'api.example', idle:{state:'active',sessionId:'s1'} },
    { id:'unlabelled', ts:'2026-01-01T10:03:00Z', app:'Maps', host:'api.example' },
    { id:'invalid-idle', ts:'2026-01-01T10:04:00Z', app:'Maps', host:'api.example', idle:{state:'idle'} },
  ]);
  assert.equal(result.idleFlows.length, 2);
  assert.equal(result.activeFlows.length, 1);
  assert.equal(result.apps.get('Maps').connections, 2);
  assert.equal(result.uploadedBytes, 200);
  assert.equal(result.destinations.get('geo.example').connections, 2);
  assert.equal(result.sensitiveSignals, 1);
});

test('identity links require the same valid pseudonymised HMAC in multiple apps', () => {
  const fingerprint = 'a'.repeat(64);
  const hit = (key, scheme='hmac-sha256', pseudonymized=true) => ({type:'adid',redacted:'•••',confidence:.9,correlation:{scheme,pseudonymized,fingerprint:key}});
  const flows = [
    { id:'f1',ts:'2026-01-01T10:00:00Z',app:'Social',host:'social.example',pii:[hit(fingerprint)] },
    { id:'f2',ts:'2026-01-01T10:02:00Z',app:'Music',host:'music.example',pii:[hit(fingerprint)] },
    { id:'f3',ts:'2026-01-01T10:03:00Z',app:'News',host:'news.example',pii:[hit('b'.repeat(64),'sha256',true)] },
    { id:'f4',ts:'2026-01-01T10:04:00Z',app:'News',host:'news.example',pii:[hit('not-a-digest')] },
  ];
  const matches = deriveIdentityCorrelations(flows);
  assert.equal(matches.length, 1);
  assert.deepEqual([...matches[0].apps].sort(), ['Music','Social']);
  assert.equal(matches[0].flows.length, 2);
  assert.deepEqual(availableCorrelationCategories(flows), ['adid']);
});

test('canonical JSON sorts object keys without changing array order', () => {
  assert.equal(canonicalJson({z:1,a:{y:2,x:3},list:[2,1]}), '{"a":{"x":3,"y":2},"list":[2,1],"z":1}');
});

test('evidence chain verifies hashes and detects modification, broken links, and missing records', async () => {
  const makeRecord = async (recordId, record, previousHash=null) => {
    const hash = await digest(canonicalJson({recordId,record,previousHash}));
    return {recordId,record,previousHash,hash};
  };
  const first = await makeRecord('r1',{event:'flow',host:'a.example'});
  const second = await makeRecord('r2',{event:'signal',type:'adid'},first.hash);
  const chain = {expectedCount:2,records:[first,second]};
  assert.equal((await verifyEvidenceChain(chain,webcrypto.subtle)).status,'verified');
  assert.equal((await verifyEvidenceChain({expectedCount:3,records:[first,second]},webcrypto.subtle)).status,'missing');
  const altered = {...chain,records:[first,{...second,record:{...second.record,type:'gps'}}]};
  assert.equal((await verifyEvidenceChain(altered,webcrypto.subtle)).status,'modified');
  assert.equal((await verifyEvidenceChain({records:[first,{...second,previousHash:'0'.repeat(64)}]},webcrypto.subtle)).status,'broken');
});

test('legal library entries have direct official source links and verification dates', () => {
  assert.ok(LEGAL_REFERENCES.length >= 3);
  for (const reference of LEGAL_REFERENCES) {
    assert.match(reference.url, /^https:\/\//);
    assert.match(reference.verified, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok(reference.authority && reference.principle && reference.relevance && reference.pinpoint);
  }
  assert.ok(LEGAL_REFERENCES.some((reference)=>reference.id==='dpdp-commencement-2025'));
});
