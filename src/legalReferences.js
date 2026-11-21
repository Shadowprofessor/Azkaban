// Primary Indian authorities, checked against their linked official publications on 22 Nov 2026.
// Summaries are GhostPrint editorial notes, not court quotations or legal advice.
export const LEGAL_REFERENCES = [
  {
    id: 'puttaswamy-2017', kind: 'Judgment', weight: 'Binding · Supreme Court', jurisdiction: 'India', topic: 'Privacy',
    title: 'Justice K.S. Puttaswamy (Retd.) v. Union of India', authority: 'Supreme Court of India', date: '2017-08-24', caseNo: 'W.P. (C) No. 494 of 2012', citation: '(2017) 10 SCC 1 · 2017 INSC 801', pinpoint: '¶ 180 (Chandrachud, J.); see also ¶ 71 (Kaul, J.)',
    principle: 'Recognised privacy as a constitutionally protected fundamental right. The opinions discuss legality, legitimate aims, proportionality, and procedural safeguards in the context of state action.',
    relevance: 'A starting point for understanding privacy principles. A network observation alone does not establish a constitutional claim against a private app or company; the actor, conduct, law, and facts matter.',
    source: 'Official Supreme Court judgment (PDF)', url: 'https://api.sci.gov.in/supremecourt/2012/35071/35071_2012_Judgement_24-Aug-2017.pdf', verified: '2026-11-22',
  },
  {
    id: 'dpdp-act-2023', kind: 'Legislation', weight: 'Central Act · phased commencement', jurisdiction: 'India', topic: 'Personal data',
    title: 'Digital Personal Data Protection Act, 2023', authority: 'Parliament of India · Act No. 22 of 2023', date: '2023-08-11', caseNo: 'Act No. 22 of 2023', citation: 'Sections 4–10, 11–17, among others', pinpoint: 'Sections 3–17; commencement notification G.S.R. 843(E)',
    principle: 'Creates a framework for processing digital personal data, including provisions on notice, consent, certain legitimate uses, data-fiduciary obligations, and individual rights.',
    relevance: 'Potentially relevant when an observed signal is personal data and the processing falls within the Act. The Gazette phases commencement: most substantive provisions listed in the notification take effect 18 months after 13 Nov 2025 (13 May 2027). Check the specific provision and current notification before relying on it.',
    source: 'India Code · official Act text', url: 'https://www.indiacode.nic.in/bitstream/123456789/22037/1/a2023-22.pdf', verified: '2026-11-22',
  },
  {
    id: 'dpdp-rules-2025', kind: 'Rules', weight: 'Central Rules · phased commencement', jurisdiction: 'India', topic: 'Personal data',
    title: 'Digital Personal Data Protection Rules, 2025', authority: 'Ministry of Electronics and Information Technology', date: '2025-11-13', caseNo: 'G.S.R. 846(E)', citation: 'G.S.R. 846(E) · Gazette of India', pinpoint: 'Rule 1(2)–(4) · commencement',
    principle: 'Sets out rules made under the DPDP Act. The notification assigns different commencement dates to different rules.',
    relevance: 'Context for understanding the Act’s implementation. The published rule states that Rules 3, 5–16, 22 and 23 commence 18 months after publication; other listed rules have earlier dates. Confirm the relevant rule and any later amendments.',
    source: 'Gazette of India · official notification (PDF)', url: 'https://egazette.gov.in/WriteReadData/2025/267650.pdf', verified: '2026-11-22',
  },
  {
    id: 'dpdp-commencement-2025', kind: 'Notification', weight: 'Official commencement notice', jurisdiction: 'India', topic: 'Commencement',
    title: 'DPDP Act commencement notification', authority: 'Ministry of Electronics and Information Technology', date: '2025-11-13', caseNo: 'G.S.R. 843(E)', citation: 'G.S.R. 843(E) · Gazette of India', pinpoint: 'Paragraphs (a)–(c)',
    principle: 'Appoints different commencement dates for provisions of the Digital Personal Data Protection Act, 2023.',
    relevance: 'Essential context before citing an Act provision. As of this source check, the notice schedules the principal data-processing and rights provisions named in paragraph (c) for 18 months after publication.',
    source: 'Gazette of India · official notification (PDF)', url: 'https://egazette.gov.in/WriteReadData/2025/267647.pdf', verified: '2026-11-22',
  },
];

export const LEGAL_TOPICS = ['All topics', 'Privacy', 'Personal data', 'Commencement'];
export const LEGAL_KINDS = ['All sources', 'Judgment', 'Legislation', 'Rules', 'Notification'];
