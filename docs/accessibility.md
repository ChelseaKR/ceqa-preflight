# Accessibility statement for reports

The HTML report is server-rendered and uses no JavaScript. It includes a
document language, semantic headings, table captions, table header scopes,
visible text status labels, and sufficient structure to remain useful when
styles are unavailable.

The PDF inspector reports technical signals such as text coverage and the
presence of a structure tree. Those signals are not an accessibility audit and
must never be represented as WCAG or PDF/UA conformance. A qualified human
review remains necessary for reading order, alternative text, color use,
tables, forms, and document meaning.

Before any public release, test representative reports with keyboard-only
navigation, VoiceOver and NVDA, browser zoom at 200%, automated checks, and a
manual WCAG 2.2 AA review. Log defects and remediation in the release record.
