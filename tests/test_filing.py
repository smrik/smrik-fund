from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from smrik_fund.ingestion.filing import (
	FilingEvidenceError,
	parse_evidence_packet,
	retrieve_filing_evidence,
	retrieve_restructuring_evidence,
	validate_evidence_refs,
)


class Section:
	def __init__(self, loc: int) -> None:
		self.loc = loc


class SearchResults:
	def __init__(self, loc: int) -> None:
		self.sections = [Section(loc)]


class Filing:
	accession_no = "0001193125-26-323660"
	form = "10-K"
	filing_date = "2026-07-29"
	report_date = "2026-06-30"
	primary_document = "msft-20260630.htm"
	text_url = "https://www.sec.gov/Archives/msft.txt"
	filing_url = "https://www.sec.gov/Archives/msft.htm"

	text_value = (
		"Header\n"
		"• Operating expenses increased $940 million or 6% driven by impairment and "
		"other related expenses in our XBOX business.\n"
		"Middle\n"
		"Research and development expenses increased $3.1 billion or 9% driven by "
		"impairment and other related expenses in our XBOX business.\n"
	)

	def text(self) -> str:
		return self.text_value

	def search(self, query: str, regex: bool = False) -> SearchResults:
		assert regex is True
		return SearchResults(196 if "Operating" in query else 201)


class FilingEvidenceTests(TestCase):
	def test_retrieval_preserves_exact_source_lines_and_provenance(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			path = Path(temporary_directory) / "restructuring.md"
			packet, metadata = retrieve_restructuring_evidence(
				Filing(), " msft ", output_path=path
			)
			parsed = parse_evidence_packet(packet, require_identity=True)
			self.assertEqual(metadata["filing_accession"], Filing.accession_no)
			self.assertEqual(metadata["evidence_file"], str(path))
			self.assertEqual(
				parsed["items"]["E1"]["excerpt"],
				"• Operating expenses increased $940 million or 6% driven by impairment and "
				"other related expenses in our XBOX business.",
			)
			self.assertEqual(
				parsed["items"]["E2"]["locator"].split(";")[0],
				"accession 0001193125-26-323660",
			)
			self.assertEqual(path.read_text(encoding="utf-8"), packet)

	def test_unknown_reference_and_malformed_packet_fail_closed(self) -> None:
		packet = (
			"Ticker: MSFT\nFiling accession: A1\nSource: filing\n\n"
			"### E1\nSource: filing\nSection: section\nLocator: accession A1; line 1\n\n"
			"> exact\n"
		)
		with self.assertRaisesRegex(FilingEvidenceError, "E99"):
			validate_evidence_refs(packet, ["E99"], require_identity=True)
		with self.assertRaises(FilingEvidenceError):
			parse_evidence_packet(
				packet.replace("### E1", "### E0"), require_identity=True
			)

	def test_discovery_literal_multi_hit_preserves_lineage_and_call_budget(self) -> None:
		class MultiHit(Filing):
			text_value = (
				"Header\n"
				"A.B [x] appears literally in one passage.\n"
				"Middle\n"
				"A.B [x] appears literally in another passage.\n"
			)

			def __init__(self) -> None:
				self.searches: list[tuple[str, bool]] = []

			def search(self, query: str, regex: bool = False) -> object:
				self.searches.append((query, regex))
				return type(
					"Results",
					(),
					{
						"sections": [
							type("Section", (), {"loc": 12, "doc": self.text_value})(),
							type("Section", (), {"loc": 19, "doc": self.text_value})(),
						]
					},
				)()

		filing = MultiHit()
		packet, metadata = retrieve_filing_evidence(
			filing, "MSFT", "literal", ["A.B [x]"],
		)
		parsed = parse_evidence_packet(packet, require_identity=True)

		self.assertEqual(filing.searches, [("A.B [x]", False)])
		self.assertEqual(metadata["evidence_item_count"], 2)
		self.assertEqual(list(parsed["items"]), ["E1", "E2"])
		for evidence in parsed["items"].values():
			self.assertIn("search section loc(s) 12, 19", evidence["locator"])
			self.assertIn("source text offsets", evidence["locator"])
			self.assertEqual(evidence["query"], "A.B [x]")
