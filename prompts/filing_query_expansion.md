# Filing Query Expansion — v1

Select zero to three short, distinctive literal phrases copied exactly from
the supplied first-pass filing evidence packet. Return each phrase with the
packet evidence IDs and one exact contiguous support span that contains it.

Use only the packet. Do not use the finding, ticker, outside knowledge,
memory, browsing, or an answer. Do not calculate, explain, map periods, infer
amounts, propose adjustments, or rewrite punctuation/case. A phrase that is
not copied verbatim from its cited excerpt must be omitted. Return an empty
list when no filing-local phrase is safe.
